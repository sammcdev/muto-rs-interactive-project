import socket, struct, io
from PIL import Image
import datetime
import speech as sp
import aiModule as g
import cv2
import threading, queue

q = queue.Queue()

# Sample code provided by instructor for receiving image
def recvall(sock, n: int) -> bytes:
    """Receive exactly n bytes or raise ConnectionError."""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Socket connection closed early")
        data += chunk
    return bytes(data)

def handle_client(conn, addr, errors):
    newTime = 0
    try:
        # Read 8-byte big-endian length
        header = recvall(conn, 8)
        (length,) = struct.unpack(">Q", header)
        # Read image payload
        payload = recvall(conn, length)

        # Turn bytes -> PIL.Image
        img = Image.open(io.BytesIO(payload)).convert("RGB")

        # Get time for unique name
        time = datetime.datetime.now()
        time = str(time)
        time = time.split(".")
        time = time[0] + "-" + time[1]
        time = time.split(":")
        newTime = ""
        for i in time:
            newTime += i
        newTime = newTime.split(" ")
        newTime = newTime[0] + "-" + newTime[1]
        
        print(f"Received image {img.size} mode={img.mode} from {addr}")
        # Do something with it: save or process
        img.save(f"{newTime}.png")
        errors = 0
    except Exception as e:
        #print("Error:", e)
        errors += 1
        # If more than 10 errors, end 
        if errors > 10:
            print('Closing connection.')
            return True, errors, newTime
    
    return False, errors, newTime

def sendRequestThread():
    # Create the server socket
    server_socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_socket.bind(('0.0.0.0', 5050)) # Bind IP and port
    server_socket.listen()
    print("Server is running... Waiting for a client to connect.")
    # Accept a client connection
    client_socket, addr = server_socket.accept()
    print(f"Client {addr} connected.")
    cmd = ''
    errors = 0
    while True:
        print('Listening...')
        while True: # Listen for keywords to trigger listening for a question
            t = sp.listen()
            if type(t) != type(None):
                t = t.lower()
                print(t)
                if 'muto' in t or 'robot' in t:
                    print('Detected...')
                    break
        sp.playMIDI(80, 127, 0.5)
        # Listen to question and save it as a string
        question = sp.listen()
        print(question)
        if type(None) == type(question): # If it is empty, say there was an error detecting speech
            sp.playMIDI(30, 127, 0.5)
            sp.playMIDI(10, 127, 0.25)
            sp.speak('There was an error detecting speech.')
        elif question.lower() == 'close program' or question.lower() == 'quit': # End program if including those key phrases
            q.put('END')
            client_socket.sendall('END'.encode())
            sp.end()
            break
        else: # If it is a valid request not asking to end the program
            intent = g.analyzeIntent(question).lower()
            q.put(intent)
            if intent == 'none':
                sp.speak(g.ask(question))
                client_socket.sendall(intent.encode())
            elif intent == 'multiple':
                sp.speak('Please narrow your request for the robot since it contains multiple actions.')
            elif intent == 'p': # If it is asking to analyze an image, tell the client on the robot to send an image
                client_socket.sendall(intent.encode())
                #camUsed = True
                print('Getting image...')
            elif intent == 'g':
                sp.speak(g.ask(question))
                client_socket.sendall(intent.encode())
            elif intent == 'w':
                sp.speak('Moving forward.')
                client_socket.sendall(intent.encode())
            elif intent == 'a':
                sp.speak('Moving left.')
                client_socket.sendall(intent.encode())
            elif intent == 's':
                sp.speak('Moving backward.')
                client_socket.sendall(intent.encode())
            elif intent == 'd':
                sp.speak('Moving right.')
                client_socket.sendall(intent.encode())
            elif intent == 'l':
                sp.speak('Rotating left.')
                client_socket.sendall(intent.encode())
            elif intent == 'r':
                sp.speak('Rotating right.')
                client_socket.sendall(intent.encode())
            elif intent == 'q':
                sp.speak('Waving.')
                client_socket.sendall(intent.encode())
            elif intent == 'sit':
                sp.speak('Sitting down.')
                client_socket.sendall(intent.encode())
            elif intent == 'lay':
                sp.speak('Laying down.')
                client_socket.sendall(intent.encode())
            elif intent == 'reset':
                sp.speak('Resetting position.')
                client_socket.sendall(intent.encode())
            elif intent == 'follow':
                sp.speak('Following.')
                client_socket.sendall(intent.encode())
            else:
                 client_socket.sendall('continue'.encode())
            sp.playMIDI(100, 127, 0.1)
        
        #if camUsed: # If the camera was used
            #ending = client_socket.recv(1024).decode() # Receive if program should be ended
            #camUsed = False
            #if ending == 'END':
                #break
    
    # Close the connection to the client and the server socket 
    client_socket.close()
    server_socket.close()
    
def handleRequestThread(): 
    # Create the server socket
    server_socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_socket.bind(('0.0.0.0', 5051)) # Bind IP and port
    server_socket.listen()
    print("Server is running... Waiting for a client to connect.")
    # Accept a client connection
    client_socket, addr = server_socket.accept()
    print(f"Client {addr} connected.")
    errors = 0
    while True:
        nxt = q.get()
        if nxt == 'END':
            break
        elif nxt == 'p':
            end, errors, newTime = handle_client(client_socket, addr, errors)
            sp.speak(g.askImage(f'{newTime}.png'))
    client_socket.close()
    server_socket.close()
    
def main():
    t1 = threading.Thread(target = sendRequestThread)
    t2 = threading.Thread(target = handleRequestThread)
    threads = [t1, t2]
    
    # Start threads
    for t in threads:
        t.start()
    
    # Wait for threads to finish
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()

