import socket
import select
import queue
import sys
import os
import re
import datetime

# create UDP socket
server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server.setblocking(0)

# Socket Select lists
inputs = [server]
outputs = []

# Server Address H2
server_ip = sys.argv[1]
server_port = int(sys.argv[2])
server_addr = (server_ip, server_port)

# bind server
server.bind(server_addr)

# Functions
def packetize(cmd, v1, v2, v3, v4, payload):
    packet = cmd + '\n'
    if(v1 != -1 and v2 != -1):
        head1 = 'Sequence: '
        head2 = 'Length: '
        packet = packet + head1 + str(v1) + '\n' + head2 + str(v2) + '\n'
    if(v3 != -1 and v4 != -1):
        head3 = 'Acknowledge: '
        head4 = 'Window: '
        packet = packet + head3 + str(v3) + '\n' + head4 + str(v4) + '\n'

    packet = packet + '\n' + payload
    # return packet.encode()
    return packet

def unpack(packet, addr):
    global recv_ackWin
    global recv_seqLen
    global recv_cmd

    switch = 0 # received ACK
    string = packet.decode()
    arr = string.split("\n")

    for line in arr:
        # command line
        if(re.search("SYN|DAT|ACK|FIN", line)):
            cmd_list = re.findall("SYN|DAT|ACK|FIN", line)
            cmd = ''
            # assemble command
            for i in range(len(cmd_list)):
                cmd += cmd_list[i]
                if(i != len(cmd_list) - 1):
                    cmd += '|'
            recv_cmd[addr] = cmd
            # receive DAT | SYN previously
            if(switch == 1 and recv_seqLen[address].empty() == False):
                # split leftover data of the previous packet from the new one
                leftover = line.split(cmd)
                recv_seqLen[addr].put(leftover[0])
            if(re.search("DAT", line)):
                switch = 1
            else:
                switch = 0
        # headers and payload        
        else:
            if(re.search("Ackno|Window", line)):
                recv_ackWin[addr].put(line)
            else:
                recv_seqLen[addr].put(line)

def get_payload(l, addr):
    global client_state
    global http_respond

    payload = ""
    while(http_respond[addr].empty() == False and len(payload) < l):
        x = http_respond[addr].get_nowait()
        payload += x

    if(http_respond[addr].empty()):
        client_state[addr] = 2
        
    return payload

def update_next(count, length, addr):
    global seq_num

    if(length == 0):
        seq_num[addr] += 1
    else:
        seq_num[addr] += length
        if(count > 1):
            seq_num[addr] += 1

# Try open file for client's request
def findFile(line, q):
    tmp = line.split()
    filename = tmp[1]
    filename = re.sub("/","",filename)
    try:
        f = open(filename)
        header1 = "HTTP/1.0 200 OK\n"
        f.close
        content_len = os.path.getsize(filename)
        header2 = 'Content length: ' + str(content_len) + '\n'
        q.put(header1 + header2)
        return filename
    except:
        q.put("HTTP/1.0 404 Not Found\n")
        return 0

# Body of p1 sws to parse requests and get respond file contents
# Store all of HTTP respond into respond_queue
def sws_exec(texts, addr):
    global respond_queue
    global http_status
    global http_tmp_status
    global http_filename
    global http_respond

    tmp_queues = queue.Queue()
    request_queues = queue.Queue()

    # Correct HTTP request formats
    format0 = "^GET\s/.*\sHTTP/1.0\r*\n"
    format1 = "connection:\s*keep-alive\r*\n"
    format2 = "connection:\s*close\r*\n"
    format3 = format0 + "(" + format1 + "|" + format2 + ")"

    arr = texts.split("\n")
    arr = arr[:len(arr)-1]
    for req in arr:
        req = req + "\n"
        tmp_queues.put(req)
    while(tmp_queues.empty() == False):
        request = tmp_queues.get_nowait()
        request_queues.put(request)
        # 1 line of request
        if request_queues.qsize() == 1:
            if(re.search(format0, request)):
                pass
            else:
                respond_queue[addr].put("HTTP/1.0 400 Bad Request\n") # respone
                respond_queue[addr].put(request) # request
                http_status[addr].put(0)
                http_filename[addr].put(0)
                #if http_tmp_status[addr] == 0:
                    #outputs.append(s)
                break

        # 2 lines in request
        if request_queues.qsize() == 2:
            line1 = request_queues.get_nowait()
            line2 = request_queues.get_nowait()
            request = line1 + line2.lower()

            if(re.search(format0 + "\r*\n", request)):
                filename = findFile(line1, respond_queue[addr]) #respone
                respond_queue[addr].put(request) # request
                http_filename[addr].put(filename) # content
                http_status[addr].put(0)
                #if http_tmp_status[addr] == 0:
                    #outputs.append(s)
                break
            elif (re.search(format3, request)):
                request_queues.put(line1)
                request_queues.put(line2)
            else:
                respond_queue[addr].put("HTTP/1.0 400 Bad Request\n") #respone
                respond_queue[addr].put(request) # request
                http_status[addr].put(0)
                http_filename[addr].put(0)
                #if http_tmp_status[addr] == 0:
                    #outputs.append(s)
                break

        # 3 lines in request       
        if request_queues.qsize() == 3:
            line1 = request_queues.get_nowait()
            line2 = request_queues.get_nowait()
            line3 = request_queues.get_nowait()
            request = line1 + line2.lower() + line3

            #if http_tmp_status[addr] == 0:
                #outputs.append(s)
            if(re.search(format3 + "\r*\n", request)):
                filename = findFile(request, respond_queue[addr]) # respone
                http_filename[addr].put(filename)
                if (re.search("alive", request)):
                    http_status[addr].put(1)
                    http_tmp_status[addr] = 1
                else:
                    http_status[addr].put(0)
                respond_queue[addr].put(request) # request 
            else:
                respond_queue[addr].put("HTTP/1.0 400 Bad Request\n") # respone
                respond_queue[addr].put(request) # request
                http_status[addr].put(0)
                http_filename[addr].put(0)   
                break

    if(http_tmp_status[addr] == 0):
        while respond_queue[addr].empty() == False:
            respone = respond_queue[addr].get_nowait()
            client_request = respond_queue[addr].get_nowait()
            f = http_filename[addr].get_nowait()

            # Send respone
            http_respond[addr].put(respone)
            status = http_status[addr].get_nowait()
            if status == 1:
                http_respond[addr].put('Connection: keep-alive\n\n')
            else:
                if http_tmp_status[addr] == 1:
                    http_respond[addr].put('Connection: close\n\n')
                else:
                    http_respond[addr].put('\n')

            # Send out file's contents
            if f != 0:
                file_obj = open(f)
                for line in file_obj:
                    for byte in line:
                        http_respond[addr].put(byte)
                file_obj.close()

            # Print log
            t = getTime()
            client_request = re.sub("\r*\n", " ", client_request)
            log = t + ": " + str(addr) + " " + client_request + "; " + respone
            print(log)
        #print(list(http_respond[addr].queue))
        #print(list(http_content[addr].queue))

def getTime():
    fmt = "%a %b %d %H:%M:%S %Z %Y"
    now = datetime.datetime.now()
    local_time = now.astimezone()
    timestring = local_time.strftime(fmt)
    return timestring

# server global variables
connected_addr = {}
seq_num = {}
ackno = {}
client_state = {}
recv_ackWin = {}
recv_seqLen = {}
recv_cmd = {}
respond_queue = {}
max_payload = int(sys.argv[4]) # MAX length of one payload
max_buffer_size = int(sys.argv[3]) # window
buffer_size = max_buffer_size
sending_queue = queue.Queue() # for writable
receiver_acked = {}
http_status = {}
http_tmp_status = {}
http_filename = {}
http_respond = {}
while True:
    readable, writable, exceptional = select.select(inputs, outputs, inputs, 7)

    # Handle inputs
    for s in readable:
        packet, address = s.recvfrom(1080)
        
        if(address not in connected_addr):
            # new client
            connected_addr[address] = True
            # add new data structure for new client
            client_state[address] = 0 # no connection yet
            seq_num[address] = 0
            ackno[address] = 0
            recv_seqLen[address] = queue.Queue()
            recv_ackWin[address] = queue.Queue()
            respond_queue[address] = queue.Queue()
            http_status[address] = queue.Queue()
            http_filename[address] = queue.Queue()
            http_respond[address] = queue.Queue()
            http_tmp_status[address] = 0
            receiver_acked[address] = {}
        
        ACK_flags = queue.Queue()
        others_flags = queue.Queue()
        respond_ACK = queue.Queue()
        respond_DAT = queue.Queue()
        unpack(packet, address)

        cmd = recv_cmd[address]
        # receive SYN|DAT|FIN
        while(recv_seqLen[address].empty() == False):
            #print(list(recv_seqLen[address].queue))
            # remove 2 empty lines resulted by unpack functions
            if not (re.search("SYN|DAT|FIN", cmd)):
                recv_seqLen[address].get_nowait()
                recv_seqLen[address].get_nowait()
                break
            # get sequence number
            head1 = recv_seqLen[address].get_nowait()
            head1 = head1.split()
            recv_seq = int(head1[1]) # recv_seq

            # get length
            head2 = recv_seqLen[address].get_nowait()
            head2 = head2.split()
            datalen = int(head2[1]) # recv_len

            if(datalen > buffer_size):
                s.sendto(b'RST', address)
                client_state[address] = -1 
                break

            # remove empty lines after headers
            recv_seqLen[address].get_nowait()
            if not (re.search("DAT", cmd)):
                recv_seqLen[address].get_nowait()

            # get PAYLOAD
            if(re.search("DAT", cmd) and datalen > 0):
                # get payload from packet
                payload = ""
                while(recv_seqLen[address].empty() == False and len(payload) < datalen):
                    payload += recv_seqLen[address].get_nowait()
                    if(len(payload) < datalen):
                        payload += '\n'     
                        if(len(payload) == datalen): # remove trailing empty space
                            recv_seqLen[address].get_nowait()
            # below acked
            if(recv_seq < ackno[address]):
                # drop, remove all the data of this packet from receiving queue
                pass
            # out of order
            elif(recv_seq != ackno[address]):
                # buffer
                receiver_acked[address][recv_seq] = payload
                ACK_flags.put('ACK')
                #respond_headers.put(ackno[address])
                #respond_headers.put(buffer_size)
            # in-order
            else: #(recv_seq == receiver_ack)
                # buffer
                receiver_acked[address][recv_seq] = payload
                while(recv_seq == ackno[address]):
                    # write to file in order data
                    payload = receiver_acked[address][recv_seq]
                    sws_exec(payload, address)
                    #f_write.write(payload)
                     # update ACK
                    if(datalen == 0):
                        ackno[address] += 1
                    else:
                        ackno[address] += len(payload)
                        if(re.search("SYN", cmd)):
                            ackno[address] += 1
                    # check previously acked packets
                    # if Key(int) in dictonary_acked
                    if(ackno[address] in receiver_acked[address]):
                        recv_seq = ackno[address]

                    # update window
                    buffer_size = buffer_size - len(payload)
                    if(buffer_size == 0):
                        buffer_size = max_buffer_size

                    ACK_flags.put('ACK')
                    respond_ACK.put(ackno[address])
                    respond_ACK.put(buffer_size)

            #if(recv_seqLen[address].empty()):
                #while(respond_flags.empty() == False):
                    #print(respond_flags.get_nowait())
                    #print('Ackno: ', respond_ACK.get_nowait())
                    #print('Window: ', respond_ACK.get_nowait())
            # check request
            # put HTTP respond to queue
            # send ACK
            # add ACK to respond packet

        # RST sent
        if(client_state[address] == -1):
            del client_state[address]
            del recv_ackWin[address]
            del recv_seqLen[address]
            del recv_cmd[address]
            del connected_addr[address]
            break

        # receive ACK
        recv_ack = 0
        recv_window = 1
        while(recv_ackWin[address].empty() == False):
            #print(list(recv_ackWin[address].queue))
            # received Ack number
            head1 = recv_ackWin[address].get_nowait()
            head1 = head1.split()
            recv_ack = int(head1[1]) # just number
            # received Window
            head2 = recv_ackWin[address].get_nowait()
            head2 = head2.split()
            recv_window = int(head2[1]) # just number
            
            if(recv_ack > 0 and client_state[address] != 2):
                client_state[address] = 1 # waiting for data -> HTTP request

            # update unacked list
            # update window list based on client's window
            # cancel timer (or not)
            
        # Send more per client's window size
        while(seq_num[address] < recv_ack + recv_window and client_state[address] != 2):
            flag_count = 0
            length = 0
            cmd_flag = ''
            payload = ''
            if(client_state[address] == 0):
                cmd_flag += 'SYN'
                flag_count += 1
                client_state[address] = 1
            if(seq_num[address] < recv_ack + recv_window):
                if(flag_count == 1):
                    cmd_flag += '|'
                cmd_flag += 'DAT'
                flag_count += 1
                payload = get_payload(max_payload, address)
                length = len(payload)
            if(client_state[address] == 2):
                if(flag_count > 1):
                    cmd_flag += '|'
                cmd_flag += 'FIN'
            others_flags.put(cmd_flag)
            respond_DAT.put(seq_num[address])
            respond_DAT.put(length)
            respond_DAT.put(payload)
            update_next(flag_count ,length, address)

        # Responding - Add packets to sending queue
        # Assemble cmd
        while(ACK_flags.empty() == False or others_flags.empty() == False):
            head1, head2, head3, head4 = -1, -1, -1, -1
            cmd_line = ''
            payload = ''
            if(ACK_flags.empty() == False):
                cmd_line += ACK_flags.get_nowait()
                head3 = respond_ACK.get_nowait()
                head4 = respond_ACK.get_nowait()
                if(others_flags.empty() == False):
                    cmd_line += '|'
                    cmd_line += others_flags.get_nowait()
                    head1 = respond_DAT.get_nowait()
                    head2 = respond_DAT.get_nowait()
                    payload = respond_DAT.get_nowait()
            else:
                cmd_line += others_flags.get_nowait()
                head1 = respond_DAT.get_nowait()
                head2 = respond_DAT.get_nowait()
                payload = respond_DAT.get_nowait()
                
            packet = packetize(cmd_line, head1, head2, head3, head4, payload)
            #print(packet)
            obj = (packet.encode(), address)
            sending_queue.put(obj)
        outputs.append(s)
            

    # Handle outputs
    for s in writable:
        while(sending_queue.empty() == False):
            p, addr = sending_queue.get_nowait()
            s.sendto(p, addr)
        outputs.remove(s)

    # timeout
    if not (readable or writable):
        print('Timeout')
        break

server.close()