* Independent 5T OTA connectivity example; dimensions are illustrative.
.subckt ota5 inp inn out vdd vss bias
M1 n1 inp tail vss nmos W=2u L=0.5u nf=2
M2 out inn tail vss nmos W=2u L=0.5u nf=2
M3 n1 n1 vdd vdd pmos W=2u L=0.5u nf=1
M4 out n1 vdd vdd pmos W=2u L=0.5u nf=1
M5 tail bias vss vss nmos W=2u L=0.5u nf=1
.ends
