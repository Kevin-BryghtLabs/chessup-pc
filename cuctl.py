#!/usr/bin/env python

from simplepyble import Adapter, Peripheral
from datetime import datetime
import time
import struct
import png

FileHeaderSize = 5
PacketHeaderSize = 2

NordicService  = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NordicRXChar   = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NordicTXChar   = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

class BLEFile:
    def __init__(self):
        self.type = None
        self.data: bytes = b''
        self.crc = 0

class ChessupBLE:
    def __init__(self):
        self.adapters: list[Adapter] = Adapter.get_adapters()
        self.boards: list[Peripheral] = []
        self.scanning = False
        self.connected = False
        self.selectedAdapter: Adapter | None = None
        self.selectedBoard: Peripheral | None = None
        self.fileMap: dict[int, BLEFile] = {}
        self.currentFileData = None
        self.images: list[png.Image] = []

    def getAdapters(self):
        return [(a.identifier(), a.address()) for a in self.adapters]

    def getBoards(self):
        return [(b.address()) for b in self.boards]

    def selectAdapter(self, address):
        self.selectedAdapter = None
        for a in self.adapters:
            if a.address() == address:
                self.selectedAdapter = a
        return self.selectedAdapter is not None

    def selectBoard(self, address):
        self.selectedBoard = None
        for b in self.boards:
            if b.address() == address:
                self.selectedBoard = b
        return self.selectedBoard is not None

    def scanBoards(self, scanTimeMs=5000):
        if self.selectedAdapter is None:
            return

        if self.scanning:
            return

        self.selectedAdapter.set_callback_on_scan_start(self.onScanStart)
        self.selectedAdapter.set_callback_on_scan_stop(self.onScanEnd)
        self.selectedAdapter.set_callback_on_scan_found(self.onPeripheralFound)

        self.selectedAdapter.scan_for(scanTimeMs)

    def onScanStart(self):
        self.scanning = True

    def onScanEnd(self):
        self.scanning = False

    def onPeripheralFound(self, p: Peripheral):
        print(f"Found peripheral {p.identifier()} [{p.address()}]")
        if p.identifier() == "ChessUp":
            self.boards.append(p)

    def connect(self):
        if self.selectedBoard is None:
            return False

        try:
            self.selectedBoard.connect()
            self.connected = True
            self.selectedBoard.notify(NordicService, NordicTXChar, self.onReceiveBLE);

        except Exception:
            return False

    def disconnect(self):
        if self.selectedBoard is None:
            return
        if not self.connected:
            return

        try:
            self.selectedBoard.disconnect()
            self.connected = False
        except Exception:
            pass

    def sendBLE(self, data):
        if self.selectedBoard is None:
            return False
        try:
            self.selectedBoard.write_request(NordicService, NordicRXChar, data);
            return True
        except Exception:
            return False

    def onReceiveBLE(self, data):
        print(f"Received BLE data type {data[0]:02x}")
        match data[0]:
            case 0xB2:
                print("Got board info")
                self.requestScreenshot()

            case 0xf4:
                self.onReceiveFileData(data)
            case _:
                pass

    def requestScreenshot(self):
        self.sendBLE(b'\xCA')

    def onReceiveFileData(self, data):
        if len(data) < PacketHeaderSize:
            print("Error: File packet too small")
            return

        fileId = data[1]

        if fileId not in self.fileMap:
            if len(data) < FileHeaderSize:
                print("Error: Initial file packet too small")
                return

            self.fileMap[fileId] = BLEFile()
            self.fileMap[fileId].type = data[2]
            (self.fileMap[fileId].crc,) = struct.unpack("<h", data[2:4])
            self.fileMap[fileId].data = data[FileHeaderSize:]

        elif len(data) > PacketHeaderSize:
            self.fileMap[fileId].data += data[PacketHeaderSize:]

        else:
            bleFile = self.fileMap.pop(fileId)
            self.handleBLEFile(bleFile)

    def handleBLEFile(self, file: BLEFile):
        (imageType,) = struct.unpack('<h', file.data[0:2])
        match imageType:
            case 0:
                self.handleRaw565(file.data[2:])
            case _:
                print("Error: Unknown image type")

    def conv565(self, data):
        (rgb565val,) = struct.unpack(">h", data)
        red   = ((rgb565val & 0xF800) >> 11) << 3
        green = ((rgb565val & 0x07E0) >>  5) << 2
        blue  = ((rgb565val & 0x001F) >>  0) << 3
        return (red, green, blue)

    def handleRaw565(self, data):
        height, width, bpp = struct.unpack('<hhh', data[0:6])
        if bpp != 16:
            print("Error: 565 data must have 16 bits per pixel")
            return

        imageSize = height * width * 2
        colorData = data[6:]

        if len(colorData) < imageSize:
            print("Error: Payload too small for header image size")
            return

        imageData=[]

        idx = 0
        for _ in range(height):
            thisRow = []
            for _ in range(width):
                thisRow += self.conv565(colorData[idx:idx+2])
                idx += 2;
            imageData.append(thisRow)

        self.images.append( png.from_array(imageData, "RGB"))
        #image.save("CUScreenshot-" + timestamp() + '.png')

    def getImages(self):
        return self.images

cu = ChessupBLE()

adapters = cu.getAdapters()
if len(adapters) == 0:
    exit(0)

cu.selectAdapter(adapters[0][1])

print("Chose {}".format(adapters[0][1]))

print("Scanning...")
cu.scanBoards()

boards = cu.getBoards()
if len(boards) == 0:
    exit(0)

device: Peripheral | None = None

for b in boards:
    if b == 'E4:B0:63:BE:75:42':
        cu.selectBoard(b)

if cu.selectedBoard is None:
    print("Target device not found")
    exit(0)

cu.connect()

for n in range(20):
    if len(cu.getImages()) > 0:
        break;
    time.sleep(1)

else:
    print("No image captured")

def timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

if (len(cu.images) > 0):
    cu.images[0].save("CUScreenshot-" + timestamp())

cu.disconnect()
