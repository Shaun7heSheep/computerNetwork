import select
import socket
import sys
import queue
import re
import datetime

# Create server socket
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setblocking(0)

# Bind socket to server's IP and Port
server_address = sys.argv[1]
server_port = sys.argv[2]
server.bind((server_address, int(server_port)))

# Listen for incoming connections
server.listen(5)

# Sockets expected to read 
inputs = [server]

# Sockets expected to write
outputs = []

# Data structures - Dictionary
message_queues = {} # Send out respone
request_queues = {} # Processing requests
tmp_queues = {} # Store stream of requets
status_queues = {} # Remember status of all requests
stat_tmp = {} # Status of prev request
content = {} # Store and send out files

# Correct HTTP request formats
format0 = "^GET\s/.*\sHTTP/1.0\r*\n"
format1 = "connection:\s*keep-alive\r*\n"
format2 = "connection:\s*close\r*\n"
format3 = format0 + "(" + format1 + "|" + format2 + ")"

# Get local time for logging
def getTime():
    fmt = "%a %b %d %H:%M:%S %Z %Y"
    now = datetime.datetime.now()
    local_time = now.astimezone()
    timestring = local_time.strftime(fmt)
    return timestring

# Try open file for client's request
def findFile(line, q):
    tmp = line.split()
    filename = tmp[1]
    filename = re.sub("/","",filename)
    try:
        f = open(filename)
        q.put("HTTP/1.0 200 OK\n")
        f.close
        return filename
    except:
        q.put("HTTP/1.0 404 Not Found\n")
        return 0

while inputs:
    # wait for at least one of the sockets to be ready for proccessing
    readable, writable, exceptional = select.select(inputs, outputs, inputs)

    # Handle inputs
    for s in readable:
        if s is server:
            # server socket is ready to accept an incoming connection
            connection, client_address = s.accept()
            connection.setblocking(0)
            inputs.append(connection)
            # Give the connection a queue for data we want to send
            message_queues[connection] = queue.Queue()
            request_queues[connection] = queue.Queue()
            tmp_queues[connection] = queue.Queue()
            content[connection] = queue.Queue()
            status_queues[connection] = queue.Queue()
            stat_tmp[connection] = 0
            message_queues[connection].put(client_address)

        else:
            data = s.recv(1024)
            if data:
                # Readable client socket has data
                texts = data.decode()
                arr = texts.split("\n")
                arr = arr[:len(arr)-1]
                for req in arr:
                    req = req + "\n"
                    tmp_queues[s].put(req)
               
            while tmp_queues[s].empty() == False:
                request = tmp_queues[s].get_nowait()
                request_queues[s].put(request)
                # 1 line of request
                if request_queues[s].qsize() == 1:
                    if(re.search(format0, request)):
                        pass
                    else:
                        message_queues[s].put("HTTP/1.0 400 Bad Request\n") # respone
                        message_queues[s].put(request) # request
                        status_queues[s].put(0)
                        content[s].put(0)
                        if stat_tmp[s] == 0:
                            outputs.append(s)
                        break

                # 2 lines in request
                if request_queues[s].qsize() == 2:
                    line1 = request_queues[s].get_nowait()
                    line2 = request_queues[s].get_nowait()
                    request = line1 + line2.lower()

                    if(re.search(format0 + "\r*\n", request)):
                        filename = findFile(line1, message_queues[s]) #respone
                        message_queues[s].put(request) # request
                        content[s].put(filename) # content
                        status_queues[s].put(0)
                        if stat_tmp[s] == 0:
                            outputs.append(s)
                        break
                    elif (re.search(format3, request)):
                        request_queues[s].put(line1)
                        request_queues[s].put(line2)
                    else:
                        message_queues[s].put("HTTP/1.0 400 Bad Request\n") #respone
                        message_queues[s].put(request) # request
                        status_queues[s].put(0)
                        content[s].put(0)
                        if stat_tmp[s] == 0:
                            outputs.append(s)
                        break 
                    
                # 3 lines in request       
                if request_queues[s].qsize() == 3:
                    line1 = request_queues[s].get_nowait()
                    line2 = request_queues[s].get_nowait()
                    line3 = request_queues[s].get_nowait()
                    request = line1 + line2.lower() + line3

                    if stat_tmp[s] == 0:
                            outputs.append(s)
                    if(re.search(format3 + "\r*\n", request)):
                        filename = findFile(request, message_queues[s]) # respone
                        content[s].put(filename)
                        if (re.search("alive", request)):
                            status_queues[s].put(1)
                            stat_tmp[s] = 1
                        else:
                            status_queues[s].put(0)
                        message_queues[s].put(request) # request 
                    else:
                        message_queues[s].put("HTTP/1.0 400 Bad Request\n") # respone
                        message_queues[s].put(request) # request
                        status_queues[s].put(0)
                        content[s].put(0)   
                        break


    for s in writable:
        log_address = message_queues[s].get_nowait()
        while message_queues[s].empty() == False:
            respone = message_queues[s].get_nowait()
            client_request = message_queues[s].get_nowait()
            f = content[s].get_nowait()

            # Send respone
            s.send(respone.encode())
            status = status_queues[s].get_nowait()
            if status == 1:
                s.send(b"Connection: keep-alive\n\n")
            else:
                if stat_tmp[s] == 1:
                    s.send(b"Connection: Closed\n\n")
                else:
                    pass

            # Send out file's contents
            if f != 0:
                obj = open(f)
                for line in obj:
                    s.send(line.encode())
                obj.close()
                    
            # Print log
            t = getTime()
            client_request = re.sub("\r*\n", " ", client_request)
            log = t + ": " + str(log_address) + " " + client_request + "; " + respone
            print(log)


        # Non-persistent connection -> Close
        if status != 1:
            outputs.remove(s)
            inputs.remove(s)
            del message_queues[s]
            del request_queues[s]
            del tmp_queues[s]
            del status_queues[s]
            del stat_tmp[s]
            del content[s]
            s.close()

        else:
            # Persistent connection -> continue listening to client
            message_queues[s].put(log_address)
        

    # Handle excecptional conditions
    for s in exceptional:
        # stop listening for input on the connection inputs.remove(s)
        if s in outputs:
            outputs.remove(s)
            s.close()
            # remove message queue
            del message_queues[s]