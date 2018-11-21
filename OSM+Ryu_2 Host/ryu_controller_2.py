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
        self.ryu2_MAC = '03:14:20:18:15:12'
        self.ryu2_IP = '192.168.100.100'
        self.Mininet_port = 1
        self.OpenStack_port = 5        
        self.client_IP = '192.168.100.81'
        self.server_IP = '192.168.100.82'
        self.scaling_MAC = '02:0a:12:14:0c:05'

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # match all flow
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        # Flow to match pii containing packets which triggers a flow installation to drop succeeding packets from the specific tcp connection
        match = parser.OFPMatch(eth_dst=self.ryu2_MAC)
        self.add_flow(datapath,100,match,actions)

        # Forward all incoming HTTP packets from the client to the OpenStack cluster
        match = parser.OFPMatch(in_port=self.Mininet_port, eth_type=0x800, ip_proto=6, ipv4_src=self.client_IP, ipv4_dst=self.server_IP)
        actions = [parser.OFPActionOutput(self.OpenStack_port)]
        self.add_flow(datapath, 1, match, actions)

        # Forward all inspected HTTP packets from the OpenStack cluster to the server
        match = parser.OFPMatch(in_port=self.OpenStack_port, eth_type=0x800, ip_proto=6, ipv4_src=self.client_IP, ipv4_dst=self.server_IP)
        actions = [parser.OFPActionOutput(self.Mininet_port)]
        self.add_flow(datapath, 1, match, actions)

        # Send packets from the scaling scripts to the load balancer (inside OpenStack cluster)
        match = parser.OFPMatch(eth_dst=self.scaling_MAC)
        actions = [parser.OFPActionOutput(self.OpenStack_port)]
        self.add_flow(datapath, 88, match, actions)


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

        if dst==self.ryu2_MAC:
            # A TCP packet containing PII forwarded by a PIID vnf
            # Install a flow to drop succeeding packets belonging to the TCP flow found to leak PII
            if (len(pkt.get_protocols(tcp.tcp))>0):
                self.logger.info("[Event]: Received a packet containing PII from a PIID\n")
                ipv4_layer = pkt.get_protocols(ipv4.ipv4)[0]
                tcp_layer = pkt.get_protocols(tcp.tcp)[0]
                match = parser.OFPMatch(eth_type=0x800, ip_proto=6, ipv4_src=ipv4_layer.src, ipv4_dst=ipv4_layer.dst, tcp_src=tcp_layer.src_port, tcp_dst=tcp_layer.dst_port)
                actions = []
                self.add_flow(datapath, 10, match,actions)
                return

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            # verify if we have a valid buffer_id, if yes avoid to send both
            # flow_mod & packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
   

   
