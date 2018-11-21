import re, sys

from mininet.cli import CLI
from mininet.log import setLogLevel, info, error
from mininet.net import Mininet
from mininet.link import Intf
from mininet.util import quietRun
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.node import UserSwitch, OVSSwitch
from mininet.topo import Topo

class SingleTopo(Topo):
    def __init__(self):
    	Topo.__init__( self )
    	client = self.addHost('c_1')
    	server = self.addHost('s_1')
    	switch = self.addSwitch('s1')
    	self.addLink(client, switch)
    	self.addLink(switch, server)        

def genericTest(topo):
    net = Mininet(topo=topo, switch=OVSSwitch)
    net.start()
    net.switches[0].cmd(" ovs-vsctl add-port s1 enp1s0 ")
    net.switches[0].cmd(" ovs-ofctl add-flow s1 'table=0, priority=1, in_port=1, dl_type=0x800, nw_proto=6, nw_src=192.168.100.81, nw_dst=192.168.100.82, actions=3' ")
    net.switches[0].cmd(" ovs-ofctl add-flow s1 'table=0, priority=1, in_port=3, dl_type=0x800, nw_proto=6, nw_src=192.168.100.81, nw_dst=192.168.100.82, actions=2' ")
    net.switches[0].cmd(" ovs-ofctl add-flow s1 'table=0, priority=0, actions=NORMAL' ")

    CLI(net, script = "mn_script")
    #CLI(net)
    net.stop()

def main():
    topo = SingleTopo()
    genericTest(topo)

if __name__ == '__main__':
    main()
