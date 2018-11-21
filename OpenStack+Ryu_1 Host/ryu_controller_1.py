# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import *
from ryu.topology.event import *
from ryu.app.ofctl.api import get_datapath
from ryu.lib import hub
from threading import Timer
import sys

class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.app_ofctl_api_app = self
        self.mac_to_port = {}
        
        self.ryu1_MAC = '03:14:20:18:15:11'
        self.ryu1_IP = '10.0.0.100'

        self.client_IP = '192.168.100.81'
        self.server_IP = '192.168.100.82'
        self.int_br_ex = 1

        self.load_balancer_MAC = None
        self.load_balancer_IP = None
        self.load_balancer_dpid = None # dpid of the switch directly conntected to the load balancer
        self.piid_dpid = {}    # dpids of the switches directly connected to PIID instances
        self.measure_tcpflowrate_thread = hub.spawn(self.request_flow_stats)
        self.tcp_flowstats={}
        self.hello_pkt_buffer=[]
        self.querying_interval=30

        self.scaling_MAC = '02:0a:12:14:0c:05'

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # match for a hello packet sent by a PII detector instance or a hello packet sent by the load balancer
        match = parser.OFPMatch(eth_dst=self.ryu1_MAC)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]        
        self.add_flow(datapath, 100, match, actions)


    def add_flow(self, datapath, priority, match,
                 actions, buffer_id=None, table_id=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst, table_id=table_id)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst, table_id=table_id)
        datapath.send_msg(mod)

    def delete_flow(self,datapath,priority,match):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        mod = parser.OFPFlowMod(datapath=datapath,priority=priority,match=match,command=ofproto.OFPFC_DELETE,out_port=ofproto.OFPP_ANY,out_group=ofproto.OFPG_ANY)
        datapath.send_msg(mod)


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # ignore lldp packet
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})

        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)

        # learn a mac address to avoid FLOOD next time.
        self.mac_to_port[dpid][src] = in_port

        if dst==self.ryu1_MAC:

            if (len(pkt.get_protocols(udp.udp))>0):
                udp_layer = pkt.get_protocols(udp.udp)[0]
                # A hello packet from a PIID vnf instance
                # Forward the packet to the load balancer to inform it of the existence of the particular PIID vnf
                if udp_layer.dst_port==2020:
                    self.logger.info("[Event]: Received Hello packet from a PIID instance\n")
                    self.piid_dpid[src]=dpid
                    if self.load_balancer_MAC==None:
                        # Keep the hello packet from the first PIID in a buffer while the load balancer vnf has not yet started 
                        self.hello_pkt_buffer.append(pkt)
                        return
                    # If the load balancer vnf is already discovered, forward the hello packet from piid to load balancer
                    self.logger.info("[Event]: Sending PIID Hello packet from controller to the Load Balancer\n")
                    self.forward_to_load_balancer(pkt)

                # A hello packet from the load balancer to inform the controller at which switch port is it connected to
                # Send the load balancer the buffered hello packet from the first piid instance   
                elif udp_layer.dst_port==2021:
                    self.logger.info("[Event]: Received Hello packet from Load Balancer\n")
                    self.load_balancer_MAC = src
                    self.load_balancer_IP = pkt.get_protocols(ipv4.ipv4)[0].src
                    self.load_balancer_dpid = dpid
                    
                    match = parser.OFPMatch(in_port=self.int_br_ex,eth_type=0x800, ip_proto=6, ipv4_src=self.client_IP, ipv4_dst=self.server_IP)
                    actions = [parser.OFPActionOutput(in_port)]
                    self.add_flow(datapath,5,match,actions)

                    match = parser.OFPMatch(in_port=in_port,eth_type=0x800, ip_proto=6, ipv4_src=self.client_IP, ipv4_dst=self.server_IP)
                    actions = [parser.OFPActionOutput(self.int_br_ex)]
                    self.add_flow(datapath,5,match,actions)

                    # Install a flow to enable the load balancer to obtain packets from the scaling script (running in the OSM host)
                    match = parser.OFPMatch(eth_dst=self.scaling_MAC)
                    actions = [parser.OFPActionOutput(in_port)]
                    self.add_flow(datapath,88,match,actions)


                    if len(self.hello_pkt_buffer)>0:
                        self.logger.info("[Event]: Sending PIID Hello packet from controller to the Load Balancer\n")
                        self.forward_to_load_balancer(self.hello_pkt_buffer.pop())
                        return
                # A flow installation request from the load balancer
                elif udp_layer.dst_port==2222:
                    # parse the payload to obtain new tcp flow to piid assignment(s)
                    # then send FlowMod messages accordingly
                    self.logger.info("[Event]: Received Flow Installation Request from the Load Balancer\n")
                    print "Redirections:",pkt[-1],"\n"
                    new_piid_tcp_assign=pkt[-1].split(';')
                    for req in new_piid_tcp_assign:
                        req_info = req.split('-')
                        tcp_flow = eval(req_info[0])
                        chosen_piid = req_info[1]
                        dpid=self.piid_dpid[chosen_piid]
                        datapath = get_datapath(self.app_ofctl_api_app,dpid)
                        chosen_piid_port=self.mac_to_port[dpid][chosen_piid]

                        # install the flow from chosen PIID to tcp server
                        match = parser.OFPMatch(in_port=chosen_piid_port, eth_type=0x800, ip_proto=6, ipv4_src=tcp_flow[0], ipv4_dst=tcp_flow[1], tcp_src=tcp_flow[2], tcp_dst=tcp_flow[3])
                        actions = [parser.OFPActionOutput(self.int_br_ex)]
                        self.add_flow(datapath,6,match,actions)

                        # install the flow from tcp client to the chosen PIID 
                        match = parser.OFPMatch(in_port=self.int_br_ex, eth_type=0x800, ip_proto=6, ipv4_src=tcp_flow[0], ipv4_dst=tcp_flow[1], tcp_src=tcp_flow[2], tcp_dst=tcp_flow[3])
                        actions = [parser.OFPActionOutput(chosen_piid_port)]
                        self.add_flow(datapath,6,match,actions)

                        if len(req_info)>2:
                            old_piid = req_info[2]
                            dpid=self.piid_dpid[old_piid]
                            old_piid_port=self.mac_to_port[dpid][old_piid]
                            match = parser.OFPMatch(in_port=old_piid_port, eth_type=0x800, ip_proto=6, ipv4_src=tcp_flow[0], ipv4_dst=tcp_flow[1], tcp_src=tcp_flow[2], tcp_dst=tcp_flow[3])
                            self.delete_flow(datapath,6,match)
                        # reset the flowstats                         
                        else:
                            self.initialize_flowstats(tcp_flow)
            return

        #if dst in self.mac_to_port[dpid]:
        #    out_port = self.mac_to_port[dpid][dst]
        #else:
        #    out_port = ofproto.OFPP_FLOOD

        #actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        #if out_port != ofproto.OFPP_FLOOD:
        #    match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            # verify if we have a valid buffer_id, if yes avoid to send both
            # flow_mod & packet_out
        #    if msg.buffer_id != ofproto.OFP_NO_BUFFER:
        #        self.add_flow(datapath, 1, match, actions, msg.buffer_id)
        #        return
        #    else:
        #        self.add_flow(datapath, 1, match, actions)
        #data = None
        #if msg.buffer_id == ofproto.OFP_NO_BUFFER:
        #    data = msg.data

        #out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
        #                          in_port=in_port, actions=actions, data=data)
        #datapath.send_msg(out)


    def initialize_flowstats(self,tcp_flow):
        self.tcp_flowstats[tcp_flow]={}
        self.tcp_flowstats[tcp_flow]["byte_count"]=0
        self.tcp_flowstats[tcp_flow]["byte_rate"]=0


    def request_flow_stats(self):
        while True:
            for dpid in set(self.piid_dpid.values()):
                datapath=get_datapath(self.app_ofctl_api_app,dpid)
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                req = parser.OFPFlowStatsRequest(datapath)                  # Request for FlowStats
                datapath.send_msg(req)
            hub.sleep(self.querying_interval)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        self.logger.info("[Event]: Received FlowStats reply from switch\n")

        dpid_port_with_piid = [self.mac_to_port[dpid][mac] for mac in self.mac_to_port[dpid] if mac in self.piid_dpid]
        reportStr={}
        for stat in sorted([flow for flow in body if (flow.priority==6)],
                           key=lambda flow: (flow.match['ipv4_src'],
                                             flow.match['ipv4_dst'],
                                             flow.match['tcp_src'],
                                             flow.match['tcp_dst'],
                                             flow.match['in_port'])):
            if (stat.match['in_port'] not in dpid_port_with_piid): 
                # flowstat of tcp flow from client to a piid instance
                tcp_flow = (stat.match['ipv4_src'],stat.match['ipv4_dst'],stat.match['tcp_src'],stat.match['tcp_dst'])
                if stat.byte_count >= self.tcp_flowstats[tcp_flow]['byte_count']:
                    self.tcp_flowstats[tcp_flow]['byte_rate']=(stat.byte_count-self.tcp_flowstats[tcp_flow]['byte_count'])*1.0/self.querying_interval
                self.tcp_flowstats[tcp_flow]['byte_count']=stat.byte_count
                reportStr[tcp_flow]=self.tcp_flowstats[tcp_flow]['byte_rate']
        # Send a flowstats report to the load balancer
        if self.load_balancer_MAC!=None and len(reportStr)>0:
            pkt = packet.Packet()
            pkt.add_protocol(ethernet.ethernet(src=self.ryu1_MAC ,dst=self.load_balancer_MAC))
            pkt.add_protocol(ipv4.ipv4(src=self.ryu1_IP,dst=self.load_balancer_IP,proto=17))
            pkt.add_protocol(udp.udp())
            pkt = pkt/str(reportStr) 
            self.logger.info("[Event]: FlowStats Report Sent to load balancer --- %s\n",str(reportStr))
            self.controller_packet_out(self.load_balancer_dpid,self.mac_to_port[self.load_balancer_dpid][self.load_balancer_MAC],pkt)

    def controller_packet_out(self,dpid,out_port,pkt):
        datapath = get_datapath(self.app_ofctl_api_app,dpid)
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        actions = [parser.OFPActionOutput(out_port)]   
        pkt.serialize()
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER, actions=actions, in_port=ofproto.OFPP_CONTROLLER, data=pkt.data)
        datapath.send_msg(out)

    # forwards PIID hello packets to the load balancer
    def forward_to_load_balancer(self,hello_pkt):
        # Overwrite the ethernet dst to the MAC address of the load balancer
        hello_pkt.get_protocols(ethernet.ethernet)[0].dst=self.load_balancer_MAC
        # Overwrite the ip dst to the IP address of the load balancer
        hello_pkt.get_protocols(ipv4.ipv4)[0].dst=self.load_balancer_IP
        self.controller_packet_out(self.load_balancer_dpid,self.mac_to_port[self.load_balancer_dpid][self.load_balancer_MAC],hello_pkt)
