sudo ovs-vsctl add-port br-ex enp2s0
sudo ifconfig enp2s0 0
sudo ifconfig br-ex '192.168.100.78'
sudo ovs-ofctl del-flows br-ex "in_port="phy-br-ex""
sudo ovs-ofctl del-flows br-int "nw_src=192.168.100.81,nw_dst=192.168.100.82,tp_dst=80"


sudo ovs-vsctl set-controller br-int tcp:127.0.0.1:6633 tcp:127.0.0.1:6653
ryu-manager Desktop/ryu_controller_1.py --ofp-tcp-listen-port 6653



