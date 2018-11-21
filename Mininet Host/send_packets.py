from scapy.all import *
import sys
import socket
import time
import os

active_interface = [intf for intf in get_if_list() if "eth" in intf][0]
ip_src = os.popen('ip addr show '+active_interface).read().split("inet ")[1].split("/")[0]
ip_dst = sys.argv[1]
sport = int(sys.argv[2])
print "Source Port: ",sport,"\n"
dport = 80

# Prevent the sender from sending RST packets 
os.popen("iptables -A OUTPUT -p tcp --tcp-flags RST RST -s "+ip_src+" -j DROP")


ether = Ether(src="01:02:12:02:01:01",dst="01:02:12:02:01:02")

ip = IP(src=ip_src,dst=ip_dst)

SYN = ether/ip/TCP(sport=sport,dport=dport,flags='S',seq=1000)

SYNACK = srp1(SYN)

time.sleep(1)

client_socket = conf.L2socket(iface=active_interface)

seq = SYNACK.ack

tracefile = rdpcap("harber.pcap")
#payload = tracefile[165][Raw].load
payload = 'GET /foo.html?user_firstname=Alice&id=17&number=18367356451&pid=621535345&key=djvbgdfhvh&search=dvbhdgfvghvdvfd872&y=7266e63edfb HTTP/1.1\r\nHost: imagevenue.com\r\nCookie: a=293&b=gdshjgfgdg&m=hsgfcgsdcvgd8736&g=00s9229daa&age=39&id=27&loc=hdfgett35&ld=hfgvghdfv&yud=ndbvgdfvsejvhh\r\nETag: 2039-2dc90ea2-12\r\nReferer: http://www.facebook.com/?user_id=89&image=6254326&uh=73632&hdfs=gfdgfhsdvds&query=hvfdgvtsftfc&_df=bdsvgdfsgcesvfcgsevcjgsdvgv&ps=vbdgfvsdvcgsdh&td=xbvg\r\nAccept-Encoding: deflate,gzip\r\n\r\n'


send_rate = int(sys.argv[3]) # in kiloBytes per second
send_delay = len(payload)/(send_rate*1000.0)

while True:
	tcp = TCP(sport=sport, dport=dport, flags='A', seq=seq, ack=SYNACK.seq + 1)
	# Wait for reply before sending another HTTP packet
	client_socket.send(ether/ip/tcp/payload)
	seq = seq + len(payload)
	time.sleep(send_delay)

