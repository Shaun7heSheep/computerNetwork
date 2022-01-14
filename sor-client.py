import socket
import select
import queue
import sys
import re
import datetime

# create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(0)

# Socket Select lists
inputs = [sock]
outputs = [sock]
err = []

# Server Address H2
server_ip = sys.argv[1]
server_port = int(sys.argv[2])
server = (server_ip, server_port)

# files
file_request = queue.Queue()
files_write = queue.Queue()
for i in range(5, len(sys.argv)):
    if (i % 2 == 1):
        file_request.put(sys.argv[i])
    else:
        files_write.put(sys.argv[i])
num_file = file_request.qsize()
writing_state = 0 # not writing anything
current_file = ''
file_length = 0
curr_len = 0

# Helper functions
def sws_exec(texts):
    global num_file
    global files_write
    global file_length
    global current_file
    global curr_len
    global writing_state

    #print(texts.encode())
    arr = texts.split('\n')
    print(arr)
    while(len(arr) > 0):
        if(writing_state == 0):
            if(re.search('200', texts)):
                writing_state = 1 # writing a file
                f = files_write.get_nowait()
                current_file = open(f, 'a')
                arr.pop(0) # HTTP respone
                content_len = arr.pop(0)
                content_len = re.findall('\d.*', content_len)
                file_length = int(content_len[0])
                if(num_file > 1):
                    arr.pop(0) # HTTP header Connection: keep-alive/ Close
                arr.pop(0) # empty line
            else:
                f = files_write.get_nowait()
                arr.pop(0) # HTP respone
                if(num_file > 1):
                    arr.pop(0) # HTTP header Connection: keep-alive/ Close
                arr.pop(0) # empty line
                arr.pop(0) # empty line

        else:
            while(curr_len < file_length and len(arr) > 0):
                data = arr.pop(0)
                curr_len += len(data)
                if(curr_len < file_length and len(arr) > 0):
                    data += '\n'
                    curr_len += 1
                current_file.write(data)
            # Finish writing 1 file
            if(curr_len == file_length or curr_len > file_length):
                writing_state = 0
                current_file.close()
    return

def unpack(string):
    global recv_ackWin
    global recv_seqLen
    global recv_cmd

    switch = 0 # receive ACK
    arr = string.split("\n")
    
    end_of_header = False
    cmd = ''
    for line in arr:
        # command line
        if(re.search("SYN|DAT|ACK|FIN",line)):
            end_of_header = False
            cmd_list = re.findall("SYN|DAT|ACK|FIN", line)
            # assemble command
            for i in range(len(cmd_list)):
                cmd += cmd_list[i]
                if(i != len(cmd_list) - 1):
                    cmd += '|'
            recv_cmd = cmd
            # receive DAT | SYN previously
            if(switch == 1 and recv_seqLen.empty() == False):
                # split leftover data of the previous packet from the new one
                leftover = line.split(cmd)
                recv_seqLen.put(leftover[0])
                print('leftover: ',leftover)
            if(re.search("DAT", line)):
                switch = 1
            else:
                switch = 0
        # headers and payload        
        else:
            if(re.search("Ackno|Window", line)):
                recv_ackWin.put(line)
            elif(re.search('Seq|Len', line)):
                recv_seqLen.put(line)
                end_of_header = True
            else:
                recv_seqLen.put(line)
                #if(end_of_header and line == ''):
                    #pass
                #else:
                    #recv_seqLen.put(line)

def packetize(cmd, payload):
    header1 = '' # seq/len
    header2 = '' # ack/win
    if(re.search("ACK", cmd)):
        header2 = 'Acknoledgement: ' + str(my_ack) + '\r\nWindow: ' + str(buffer_size) + '\r\n'
    if(re.search("SYN|DAT|FIN", cmd)):
        header1 = 'Sequence: ' + str(seq_num) + '\r\nLength: ' + str(len(payload)) + '\r\n'

    packet = cmd + '\r\n' + header1 + header2 + '\r\n' + payload
    return packet

def update_next(cmd, length):
    global seq_num
    global my_ack

    if(length == 0):
        seq_num += 1
    else:
        seq_num += length
        if(re.search("SYN", cmd)):
            seq_num += 1
            my_ack += 1

def get_payload(l):
    global client_state
    global file_request
    payload = ""

    while(file_request.empty() == False and len(payload) + 50 < l):
        filename = file_request.get_nowait()
        payload += 'GET /' + filename + ' HTTP/1.0\r\n'
        if(file_request.empty() == False):
            payload += 'Connection: keep-alive\r\n\r\n'
        else:
            payload += '\r\n'

    if(file_request.empty()):
        client_state = 2
        
    return payload

def getTime():
    fmt = "%a %b %d %H:%M:%S %Z %Y"
    now = datetime.datetime.now()
    local_time = now.astimezone()
    timestring = local_time.strftime(fmt)
    return timestring

def printLog(state, cmd, v1, v2, v3, v4):
    head1, head2, head3, head4 = '', '', '', ''

    t = getTime()
    tmp_log1, tmp_log2 = '',''
    if(re.search("SYN|DAT|FIN", cmd)):
        head1 = 'Sequence: '
        head2 = 'Length: '
        tmp_log1 = '; ' + head1 + str(v1) + '; ' + head2 + str(v2)
    if(re.search("ACK", cmd)):
        head3 = 'Acknowledge: '
        head4 = 'Window: '
        tmp_log2 = '; ' + head3 + str(v3) + '; ' + head4 + str(v4)

    log = t + '; ' + state + '; ' + cmd + tmp_log1 + tmp_log2
    print(log)

# variables received from server
recv_window = 1
recv_ack = 0
recv_cmd = ''
recv_ackWin = queue.Queue()
recv_seqLen = queue.Queue()

# Client's global var
seq_num = 0
last_seq = -1
my_ack = -1
client_state = 0 # no connection yet
closing_state = False # waiting for last ACK
max_payload = int(sys.argv[4]) # MAX length of one payload
max_buffer_size = int(sys.argv[3]) # window
buffer_size = max_buffer_size

# data structures
commands_list = queue.Queue()
receiver_acked = {}
unacked_packet = {}
unacked_seq = []

#cond = True
while True:
    readable, writable, exceptional = select.select(inputs, outputs, err, 2)

    for s in writable:
        sending = queue.Queue()
        while(seq_num < recv_ack + recv_window and client_state != 2):
            cmd = ''
            payload = ''
            length = 0
            if(client_state == 0):
                commands_list.put('SYN')
            if(file_request.empty() == False):
                payload = get_payload(max_payload)
                #print(payload.encode())
                length = len(payload)
                commands_list.put('DAT')

            commands_list.put('ACK')

            if(file_request.empty()):
                commands_list.put('FIN')
                last_seq = seq_num
                client_state = 2 # waiting for FIN from server

            # Assemble command line
            while(commands_list.empty() == False):
                cmd += commands_list.get_nowait()
                if(commands_list.empty() == False):
                    cmd += '|'
            packet = packetize(cmd, payload)
            # store unacked
            unacked_seq.append(seq_num)
            unacked_packet[seq_num] = packet

            sending.put(packet)
            printLog('send', cmd, seq_num, length, my_ack, buffer_size)
            update_next(cmd, length)

        while(sending.empty() == False):
            p = sending.get_nowait()
            s.sendto(p.encode(), server)
        outputs.remove(s)


    for s in readable:
        encoded_packet = s.recv(1120)
        packet = encoded_packet.decode()
        #print(packet)

        if(re.search("RST", packet)):
            t = getTime()
            print(t + '; receive; RST')
            del recv_seqLen
            del recv_ackWin
            del commands_list
            s.close()
            exit(0)

        ACK_flags = queue.Queue()
        others_flags = queue.Queue()
        respond_ACK = queue.Queue()
        respond_DAT = queue.Queue()
        receiver_out = queue.Queue()

        unpack(packet)
        cmd = recv_cmd

        # receive SYN|DAT|FIN
        while(recv_seqLen.empty() == False):
            if not (re.search("SYN|DAT|FIN", cmd)):
                recv_seqLen.get_nowait()
                recv_seqLen.get_nowait()
                break
            # get sequence number
            head1 = recv_seqLen.get_nowait()
            head1 = head1.split()
            recv_seq = int(head1[1])

            # get length
            head2 = recv_seqLen.get_nowait()
            head2 = head2.split()
            datalen = int(head2[1])

            # remove empty lines after headers
            recv_seqLen.get_nowait()
            if not (re.search("DAT", cmd)):
                recv_seqLen.get_nowait()

            if(re.search('FIN', cmd)):
                closing_state = True

            # get PAYLOAD
            if(re.search("DAT", cmd) and datalen > 0):
                # get payload from packet
                payload = ""
                while(recv_seqLen.empty() == False and len(payload) < datalen):
                    payload += recv_seqLen.get_nowait()
                    if(len(payload) < datalen):
                        payload += '\n'     
                        if(len(payload) == datalen): # remove trailing empty space
                            recv_seqLen.get_nowait()
            # below acked
            if(recv_seq < my_ack):
                # drop, remove all the data of this packet from receiving queue
                pass
            # out of order
            elif(recv_seq != my_ack):
                # buffer
                receiver_acked[recv_seq] = payload
                ACK_flags.put('ACK')
            # in-order
            else: #(recv_seq == receiver_ack)
                # buffer
                receiver_acked[recv_seq] = payload
                while(recv_seq == my_ack):
                    # write to file in order data
                    payload = receiver_acked[recv_seq] # this is RDP-payload
                    sws_exec(payload)
                    #f_write.write(payload)
                     # update ACK
                    if(datalen == 0):
                        my_ack += 1
                    else:
                        my_ack += len(payload)
                        if(re.search("SYN", cmd)):
                            my_ack += 1
                    # check previously acked packets
                    # if Key(int) in dictonary_acked
                    if(my_ack in receiver_acked):
                        recv_seq = my_ack

                    # update window
                    buffer_size = buffer_size - len(payload)
                    if(buffer_size == 0):
                        buffer_size = max_buffer_size

                    packet = packetize('ACK', '')
                    receiver_out.put(packet)
                    ACK_flags.put('ACK')
                    respond_ACK.put(my_ack)
                    respond_ACK.put(buffer_size)

        # receive ACK            
        while(recv_ackWin.empty() == False):
            #print(list(recv_ackWin[address].queue))
            # received Ack number
            head1 = recv_ackWin.get_nowait()
            head1 = head1.split()
            recv_ack = int(head1[1]) # just number
            # received Window
            head2 = recv_ackWin.get_nowait()
            head2 = head2.split()
            recv_window = int(head2[1]) # just number

            if(recv_ack > 0 and client_state != 2):
                client_state = 1

        printLog('receive', cmd, recv_seq, datalen, recv_ack, recv_window)

        # respond ACK ; Send ACK
        while(ACK_flags.empty()==False):
            t = getTime()
            cmd = ACK_flags.get_nowait()
            ack = str(respond_ACK.get_nowait())
            window = str(respond_ACK.get_nowait())
            p = receiver_out.get_nowait()
            s.sendto(p.encode(), server)
            log = t + '; send; ' + cmd + '; Acknowledge: ' + ack + '; Window: ' + window
            print(log)

        outputs.append(s)

    if not (writable or readable):
        if(closing_state == True):
            break
        else:
            print('Timeout - Resend oldest packet')

sock.close()