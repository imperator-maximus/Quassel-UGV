import serial 
import time 
 
def main(): 
    ser = serial.Serial('COM7', 115200, timeout=1) 
    print('Serielle Überwachung gestartet. Drücken Sie Ctrl+C zum Beenden.') 
    try: 
        while True: 
            if ser.in_waiting: 
                line = ser.readline().decode('utf-8', errors='ignore').strip() 
                if line: 
                    print(line) 
            time.sleep(0.1) 
    except KeyboardInterrupt: 
        print('Beendet') 
    finally: 
        ser.close() 
 
if __name__ == "__main__": 
    main() 
