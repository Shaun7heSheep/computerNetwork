import socket
import select
import sys
import queue
import re
import datetime

# create socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(0)

# bind socket
ip_addr = sys.argv[1]
port_number = int(sys.argv[2])
sock.bind((ip_addr, port_number))

# Echo server
h2 = ('10.10.1.100', 8888)

# files
read_file_name = sys.argv[3]
write_file_name = sys.argv[4]
try:
    f_read = open(read_file_name, 'r')
    f_write = open(write_file_name, 'a')

    content = queue.Queue()
    for line in f_read:
        for letter in line:
            content.put(letter)

    f_read.close()
except:
    print('cannot open file')

# create a packet with CMD, V1, V2, PAYLOAD
def packetize(cmd, v1, v2, payload):
    if(cmd == 'ACK'):
        head1 = 'Acknowledge: '
        head2 = 'Window: '
    else:
        head1 = 'Sequence: '
        head2 = 'Length: '

    packet = cmd + '\n' + head1 + str(v1) + '\n' + head2 + str(v2) + '\n\n' + payload
    return packet.encode()

def get_payload(l):
    global sender_state
    global content
    payload = ""
    while(content.empty() == False  and len(payload) < l):
        x = content.get_nowait()
        payload += x

    if(content.empty()):
        sender_state = 2
        
    return payload

# unload big packets into 2 different queues ACK <> DAT
def unpack(packet):
    global receiving

    switch = 0 # received ACK
    string = packet.decode()
    arr = string.split("\n")
    for e in arr:
        if(re.search("SYN|DAT|FIN", e)):
            cmd = re.findall("SYN|DAT|FIN", e)
            # receive DAT | SYN previously
            if(switch == 1 and receiving['DAT'].empty() == False):
                # split leftover data of the previous packet from the new one
                leftover = e.split(cmd[0])
                receiving['DAT'].put(leftover[0])
            receiving['DAT'].put(cmd[0])
            switch = 1
        elif(re.search("ACK", e)):
            cmd = re.findall("ACK", e)
            switch = 0
            receiving['ACK'].put(cmd[0])
        else:
            if(switch == 0):
                receiving['ACK'].put(e)
            else:
                receiving['DAT'].put(e)

def getTime():
    fmt = "%a %b %d %H:%M:%S %Z %Y"
    now = datetime.datetime.now()
    local_time = now.astimezone()
    timestring = local_time.strftime(fmt)
    return timestring
                
def printLog(state, cmd, v1, v2):
    t = getTime()
    if(cmd == 'ACK'):
        head1 = 'Acknowledge: '
        head2 = 'Window: '
    else:
        head1 = 'Sequence: '
        head2 = 'Length: '

    log = t + '; ' + state + '; ' + cmd + '; ' + head1 + str(v1) + '; ' + head2 + str(v2)
    print(log)

# Update the next Sequence number that the sender will send next
# Update sender window based on what it has sent
def update_next():
    global sequence
    global length

    if(length == 0):
        sequence += 1
    else:
        sequence += length


# Socket Select lists
inputs = [sock]
outputs = [sock]
err = []

# buffer
receiving = {}
receiving['ACK'] = queue.Queue()
receiving['DAT'] = queue.Queue()
sending = queue.Queue()
receiver_out = queue.Queue()

unacked_list = []
sender_unacked = {}
receiver_acked = {}

# window_size
receiver_window = 3072
sender_window = 1

# acknowledge
receiver_ack = 0

sender_state = 0 # 0 = not connected; 1 = connected and send data; 2 = closing
last_seq = -1
command = 'SYN'
sequence = 0
length = 0


base = True
while base:
    readable, writable, exceptional = select.select(inputs, outputs, err, 3)

    # On application write
    for s in writable:
        # send packets per window_size
        while(sequence < receiver_ack + sender_window and sender_state != 2):
            if(sender_state == 1):
                command = 'DAT'
                payload = get_payload(1024)
                length = len(payload)
            else:
                payload = ""
                length = 0
                if(command == 'FIN'):
                    last_seq = sequence
                    sender_state = 2
            packet = packetize(command, sequence, length, payload)
            sending.put(packet)
            printLog('send', command, sequence, length)
            # store unacked
            unacked_list.append(sequence)
            sender_unacked[sequence] = packet
            update_next()
            
        while(sending.empty() == False):
            p = sending.get_nowait()
            s.sendto(p, h2)
        outputs.remove(s)

    # On Receiving
    for s in readable:
        packet = s.recv(3180) # window_size is 2048
        unpack(packet)
        # Receiver receive DAT|SYN|FIN
        while(receiving['DAT'].empty()==False):
            cmd = receiving['DAT'].get()
            # received Sequence number
            head1 = receiving['DAT'].get()
            head1 = head1.split()
            recv_seq = int(head1[1]) # just number
            # received Length
            head2 = receiving['DAT'].get()
            head2 = head2.split()
            recv_len = int(head2[1]) # just number
            
            # remove empty lines after headers
            receiving['DAT'].get()
            if(cmd != 'DAT'):
                receiving['DAT'].get()

            if(cmd == 'DAT' and recv_len > 0):
                # get payload from packet
                payload = ""
                while(receiving['DAT'].empty() == False and len(payload) < recv_len):
                    payload += receiving['DAT'].get()
                    if(len(payload) < recv_len):
                        payload += '\n'     
                        if(len(payload) == recv_len): # remove trailing empty space
                            receiving['DAT'].get()
            printLog('receive', cmd, recv_seq, recv_len)

            # below acked
            if(recv_seq < receiver_ack):
                # drop, remove all the data of this packet from receiving queue
                packet = packetize("ACK", receiver_ack, receiver_window, "") 
                receiver_out.put(packet)
                printLog('send', 'ACK', receiver_ack, receiver_window)
            # beyond acked + window
            elif(recv_seq > receiver_ack + receiver_window):
                # Send RST and exit
                pass
            # out of order
            elif(recv_seq != receiver_ack):
                # buffer
                receiver_acked[recv_seq] = payload
                packet = packetize("ACK", receiver_ack, receiver_window, "") 
                receiver_out.put(packet)
                printLog('send', 'ACK', receiver_ack, receiver_window)
            # in-order
            else: #(recv_seq == receiver_ack)
                # buffer
                receiver_acked[recv_seq] = payload
                while(recv_seq == receiver_ack):
                    # write to file in order data
                    payload = receiver_acked[recv_seq]
                    f_write.write(payload)

                    # update ACK
                    if(recv_len == 0):
                        receiver_ack += 1
                    else:
                        receiver_ack += len(payload)
                    # check previously acked packets
                    # if Key(int) in dictonary_acked
                    if(receiver_ack in receiver_acked):
                        recv_seq = receiver_ack

                    # update window
                    receiver_window = receiver_window - len(payload)
                    if(receiver_window == 0):
                        receiver_window = 3072

                    packet = packetize("ACK", receiver_ack, receiver_window, "") 
                    receiver_out.put(packet)
                    printLog('send', 'ACK', receiver_ack, receiver_window)
                    
            if(receiving['DAT'].empty()):
                # send ACK
                while(receiver_out.empty()==False):
                    p = receiver_out.get()
                    s.sendto(p, h2)

        # On receiving ACK
        while(receiving['ACK'].empty() == False):
            cmd = receiving['ACK'].get()
            if(cmd==""):
                break
            # received Ack number
            head1 = receiving['ACK'].get()
            head1 = head1.split()
            recv_ack = int(head1[1]) # just number
            # received Length
            head2 = receiving['ACK'].get()
            head2 = head2.split()
            recv_window = int(head2[1]) # just number
            sender_window = recv_window

            # remove empty lines
            receiving['ACK'].get()
            
            if(recv_ack > 0 and sender_state != 2):
                sender_state = 1

            printLog('receive', cmd, recv_ack, recv_window)
            for seq_num in unacked_list:
                if(seq_num < recv_ack):
                    unacked_list.remove(seq_num)
                    del sender_unacked[seq_num]
                    
            if(sender_state == 2 and len(sender_unacked) == 0):
                command = 'FIN'
                sender_state = 0
            # Closing transmission
            if(recv_ack-1 == last_seq):
                inputs.remove(s)
                base = False
                break    
            if(recv_window > 0):
                outputs.append(s)

    # On timeout
    if not (readable or writable or exceptional):
        oldest_seq = min(unacked_list)
        oldest_packet = sender_unacked[oldest_seq]
        sock.sendto(oldest_packet, h2)
        tmp = oldest_packet.split()
        cmd = tmp[0].decode()
        seq = tmp[2].decode()
        l = tmp[4].decode()
        printLog('send', cmd, seq, l)
        continue

f_write.close()
sock.close()