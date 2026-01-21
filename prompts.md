# Prompt Library (200 Mixed Prompts)

## Flexible Prompts That Work (Recommended)

### RAG (read-only / no execution)
- Show test case TC-1198
- Find test case TC-15174
- List steps for TC-1198
- Show detailed steps for TC-15174
- List all test cases
- List SPDM test cases
- List PCIe SSD hotplug test cases
- Show systems in rack B19
- List hosts in rack D1
- Find system with service tag 98HLZ85

### Live RAG (SSH / command execution)
- Get `dmesg | tail -n 200` from aseda-VMware-Vm1
- Run `lscpu` on aseda-VMware-Vm1
- /live dmesg aseda-VMware-Vm1
- /live lspci aseda-VMware-Vm1
- /live nvme aseda-VMware-Vm1
- Find nvme errors in 98HLZ86
- /live nvme-errors 98HLZ86

### Testcase execution (requires host)
- Run testcase TC-3362 on host 98HLZ85
- Run testcase DSSTC-5351 on host 98HLZ85 device /dev/nvme0n1
- Run testcase TC-3362 on host 98HLZ85 in background

### Audit (post-run logs)
- /audit testcase TC-15174 log path /home/aseda/project/sena_try/data/exports/run_TC-15174_98HLZ85_20260120T201713Z

## Testcase + Firmware Prompts (How-to)

- Run testcase TC-3362 on host 98HLZ85
- Run testcase DSSTC-5351 on host 98HLZ85 device /dev/nvme0n1
Audit existing logs by path: Audit testcase TC-15174 log path /home/aseda/project/sena_try/data/exports/run_TC-15174_98HLZ85_20260120T201713Z
Run in background: Run testcase TC-3362 on host 98HLZ85 in background
Check status: /test status TC-3362 98HLZ85
Get logs: /test log TC-3362 98HLZ85
- Run testcase TC-3362 on host aseda-VMware-Vm1
- Run testcase TC-3362 on host 98HLZ85 and analyze failures
- Update firmware version 007S on rack D1 (dry-run)
- Update firmware version 007S on rack D1 execute
- Update firmware version 007S on host 98HLZ85
- Update firmware version 007S on host 98HLZ85 execute
- /test status
- /test status TC-3362 98HLZ85
- /test log TC-3362 98HLZ85

1) Get dmesg | tail -n 200 from aseda-VMware-Vm1
2) Run dmesg | tail -n 200 on aseda-VMware-Vm1
3) Summarize dmesg | tail -n 200 from aseda-VMware-Vm1
4) Get dmesg | tail -n 50 from aseda-VMware-Vm1
5) Run dmesg | tail -n 50 on aseda-VMware-Vm1
6) Summarize dmesg | tail -n 50 from aseda-VMware-Vm1
7) Get lscpu from aseda-VMware-Vm1
8) Run lscpu on aseda-VMware-Vm1
9) Summarize lscpu from aseda-VMware-Vm1
10) Get lspci -nn from aseda-VMware-Vm1
11) Run lspci -nn on aseda-VMware-Vm1
12) Summarize lspci -nn from aseda-VMware-Vm1
13) Get lspci -vv from aseda-VMware-Vm1
14) Run lspci -vv on aseda-VMware-Vm1
15) Summarize lspci -vv from aseda-VMware-Vm1
16) Get lsblk -o NAME,SIZE,MODEL,SERIAL from aseda-VMware-Vm1
17) Run lsblk -o NAME,SIZE,MODEL,SERIAL on aseda-VMware-Vm1
18) Summarize lsblk -o NAME,SIZE,MODEL,SERIAL from aseda-VMware-Vm1
19) Get ip -4 addr show from aseda-VMware-Vm1
20) Run ip -4 addr show on aseda-VMware-Vm1
21) Summarize ip -4 addr show from aseda-VMware-Vm1
22) Get nvme list from aseda-VMware-Vm1
23) Run nvme list on aseda-VMware-Vm1
24) Summarize nvme list from aseda-VMware-Vm1
25) Get journalctl -k -p 3 -b --no-pager | tail -n 200 from aseda-VMware-Vm1
26) Run journalctl -k -p 3 -b --no-pager | tail -n 200 on aseda-VMware-Vm1
27) Summarize journalctl -k -p 3 -b --no-pager | tail -n 200 from aseda-VMware-Vm1
28) Get dmesg | tail -n 200 from host-b1
29) Run dmesg | tail -n 200 on host-b1
30) Summarize dmesg | tail -n 200 from host-b1
31) Get dmesg | tail -n 50 from host-b1
32) Run dmesg | tail -n 50 on host-b1
33) Summarize dmesg | tail -n 50 from host-b1
34) Get lscpu from host-b1
35) Run lscpu on host-b1
36) Summarize lscpu from host-b1
37) Get lspci -nn from host-b1
38) Run lspci -nn on host-b1
39) Summarize lspci -nn from host-b1
40) Get lspci -vv from host-b1
41) Run lspci -vv on host-b1
42) Summarize lspci -vv from host-b1
43) Get lsblk -o NAME,SIZE,MODEL,SERIAL from host-b1
44) Run lsblk -o NAME,SIZE,MODEL,SERIAL on host-b1
45) Summarize lsblk -o NAME,SIZE,MODEL,SERIAL from host-b1
46) Get ip -4 addr show from host-b1
47) Run ip -4 addr show on host-b1
48) Summarize ip -4 addr show from host-b1
49) Get nvme list from host-b1
50) Run nvme list on host-b1
51) Summarize nvme list from host-b1
52) Get journalctl -k -p 3 -b --no-pager | tail -n 200 from host-b1
53) Run journalctl -k -p 3 -b --no-pager | tail -n 200 on host-b1
54) Summarize journalctl -k -p 3 -b --no-pager | tail -n 200 from host-b1
55) Get dmesg | tail -n 200 from host-b19
56) Run dmesg | tail -n 200 on host-b19
57) Summarize dmesg | tail -n 200 from host-b19
58) Get dmesg | tail -n 50 from host-b19
59) Run dmesg | tail -n 50 on host-b19
60) Summarize dmesg | tail -n 50 from host-b19
61) Get lscpu from host-b19
62) Run lscpu on host-b19
63) Summarize lscpu from host-b19
64) Get lspci -nn from host-b19
65) Run lspci -nn on host-b19
66) Summarize lspci -nn from host-b19
67) Get lspci -vv from host-b19
68) Run lspci -vv on host-b19
69) Summarize lspci -vv from host-b19
70) Get lsblk -o NAME,SIZE,MODEL,SERIAL from host-b19
71) Run lsblk -o NAME,SIZE,MODEL,SERIAL on host-b19
72) Summarize lsblk -o NAME,SIZE,MODEL,SERIAL from host-b19
73) Get ip -4 addr show from host-b19
74) Run ip -4 addr show on host-b19
75) Summarize ip -4 addr show from host-b19
76) Get nvme list from host-b19
77) Run nvme list on host-b19
78) Summarize nvme list from host-b19
79) Get journalctl -k -p 3 -b --no-pager | tail -n 200 from host-b19
80) Run journalctl -k -p 3 -b --no-pager | tail -n 200 on host-b19
81) Summarize journalctl -k -p 3 -b --no-pager | tail -n 200 from host-b19
82) Get dmesg | tail -n 200 from host-rackD
83) Run dmesg | tail -n 200 on host-rackD
84) Summarize dmesg | tail -n 200 from host-rackD
85) Get dmesg | tail -n 50 from host-rackD
86) Run dmesg | tail -n 50 on host-rackD
87) Summarize dmesg | tail -n 50 from host-rackD
88) Get lscpu from host-rackD
89) Run lscpu on host-rackD
90) Summarize lscpu from host-rackD
91) Get lspci -nn from host-rackD
92) Run lspci -nn on host-rackD
93) Summarize lspci -nn from host-rackD
94) Get lspci -vv from host-rackD
95) Run lspci -vv on host-rackD
96) Summarize lspci -vv from host-rackD
97) Get lsblk -o NAME,SIZE,MODEL,SERIAL from host-rackD
98) Run lsblk -o NAME,SIZE,MODEL,SERIAL on host-rackD
99) Summarize lsblk -o NAME,SIZE,MODEL,SERIAL from host-rackD
100) Get ip -4 addr show from host-rackD
101) Run ip -4 addr show on host-rackD
102) Summarize ip -4 addr show from host-rackD
103) Get nvme list from host-rackD
104) Run nvme list on host-rackD
105) Summarize nvme list from host-rackD
106) Get journalctl -k -p 3 -b --no-pager | tail -n 200 from host-rackD
107) Run journalctl -k -p 3 -b --no-pager | tail -n 200 on host-rackD
108) Summarize journalctl -k -p 3 -b --no-pager | tail -n 200 from host-rackD
109) Get dmesg | tail -n 200 from lab-node-01
110) Run dmesg | tail -n 200 on lab-node-01
111) Summarize dmesg | tail -n 200 from lab-node-01
112) Get dmesg | tail -n 50 from lab-node-01
113) Run dmesg | tail -n 50 on lab-node-01
114) Summarize dmesg | tail -n 50 from lab-node-01
115) Get lscpu from lab-node-01
116) Run lscpu on lab-node-01
117) Summarize lscpu from lab-node-01
118) Get lspci -nn from lab-node-01
119) Run lspci -nn on lab-node-01
120) Summarize lspci -nn from lab-node-01
121) Get lspci -vv from lab-node-01
122) Run lspci -vv on lab-node-01
123) Summarize lspci -vv from lab-node-01
124) Get lsblk -o NAME,SIZE,MODEL,SERIAL from lab-node-01
125) Run lsblk -o NAME,SIZE,MODEL,SERIAL on lab-node-01
126) Summarize lsblk -o NAME,SIZE,MODEL,SERIAL from lab-node-01
127) Get ip -4 addr show from lab-node-01
128) Run ip -4 addr show on lab-node-01
129) Summarize ip -4 addr show from lab-node-01
130) Get nvme list from lab-node-01
131) Run nvme list on lab-node-01
132) Summarize nvme list from lab-node-01
133) Get journalctl -k -p 3 -b --no-pager | tail -n 200 from lab-node-01
134) Run journalctl -k -p 3 -b --no-pager | tail -n 200 on lab-node-01
135) Summarize journalctl -k -p 3 -b --no-pager | tail -n 200 from lab-node-01
136) /live dmesg aseda-VMware-Vm1
137) /live dmesg raw aseda-VMware-Vm1
138) /live dmesg full aseda-VMware-Vm1
139) /live lscpu aseda-VMware-Vm1
140) /live lspci aseda-VMware-Vm1
141) /live lsblk aseda-VMware-Vm1
142) /live ip aseda-VMware-Vm1
143) /live nvme aseda-VMware-Vm1
144) /live journal aseda-VMware-Vm1
145) /live dmesg host-b1
146) /live dmesg raw host-b1
147) /live dmesg full host-b1
148) /live lscpu host-b1
149) /live lspci host-b1
150) /live lsblk host-b1
151) /live ip host-b1
152) /live nvme host-b1
153) /live journal host-b1
154) /live dmesg host-b19
155) /live dmesg raw host-b19
156) /live dmesg full host-b19
157) /live lscpu host-b19
158) /live lspci host-b19
159) /live lsblk host-b19
160) /live ip host-b19
161) /live nvme host-b19
162) /live journal host-b19
163) /live dmesg host-rackD
164) /live dmesg raw host-rackD
165) /live dmesg full host-rackD
166) /live lscpu host-rackD
167) /live lspci host-rackD
168) /live lsblk host-rackD
169) /live ip host-rackD
170) /live nvme host-rackD
171) /live journal host-rackD
172) /live dmesg lab-node-01
173) /live dmesg raw lab-node-01
174) /live dmesg full lab-node-01
175) /live lscpu lab-node-01
176) /live lspci lab-node-01
177) /live lsblk lab-node-01
178) /live ip lab-node-01
179) /live nvme lab-node-01
180) /live journal lab-node-01
181) Summarize the issues from that output
182) Show the error lines only
183) What are the critical errors?
184) Explain the warnings in that log
185) Which lines look suspicious?
186) List the top 5 issues with timestamps
187) Summarize dmesg issues
188) Show only DENIED or audit lines
189) List all AppArmor denials
190) Find link flaps or NIC errors
191) Explain hogged CPU messages
192) Show lines related to NVMe
193) /live last full
194) /live last summary
195) /live errors
196) /live summarize
197) Show test case TC-1198
198) List steps only for TC-1198
199) Show detailed steps for TC-1198
200) Find test case TC-1198
