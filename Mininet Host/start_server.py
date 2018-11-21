from scapy.all import *
import socket
import os

active_interface = [intf for intf in get_if_list() if "e" in intf][0]
ip_addr = os.popen('ip addr show '+active_interface).read().split("inet ")[1].split("/")[0]

server_socket = conf.L3socket(iface=active_interface)

def reply(packet):
	global server_socket
	ip = IP(src=packet[IP].dst,dst=packet[IP].src)
	ack = packet[TCP].seq

	# reply to SYN packets
	if packet[TCP].flags==2:
		flag='SA'
		seq = 2000	
		ack += 1
	# send ACK for HTTP packets
	else:
		flag = 'A'
		seq = packet[TCP].ack
		ack += len(packet[TCP].payload)

	reply_pkt = ip/TCP(sport=packet[TCP].dport,dport=packet[TCP].sport,flags=flag,seq=seq,ack=ack)
	server_socket.send(reply_pkt)
	return

sniff(iface=active_interface,prn=reply,filter='tcp and ip dst host '+ip_addr)