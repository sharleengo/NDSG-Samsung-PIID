from scapy.all import *
import socket

active_interface = [intf for intf in get_if_list() if "e" in intf][0]
vnf_name = socket.gethostname()

def write_to_pcap(pkt):
	global vnf_name
	wrpcap(vnf_name+"_trace", pkt, append=True)  #appends packet to output file


sniff(iface=active_interface, prn=write_to_pcap, store=0)
