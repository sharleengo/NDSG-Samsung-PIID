from scapy.all import *

active_interface = [intf for intf in get_if_list() if "-et" in intf][0]
vnf_name = active_interface[0:active_interface.index("-et")]

def write_to_pcap(pkt):
	global vnf_name
	wrpcap(vnf_name+"_trace", pkt, append=True)  #appends packet to output file


sniff(iface=active_interface, prn=write_to_pcap, store=0)