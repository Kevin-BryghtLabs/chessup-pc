#!/usr/bin/env python

import png
import signal
import struct
import traceback

from io import BytesIO
from multiprocessing import Pipe, Process, freeze_support
from simplepyble import Adapter, Peripheral

class BLEFile:
    def __init__(self):
        self.type = None
        self.data: bytes = b''
        self.crc = 0

class Board:
    def __init__(self, address, rssi):
        self.address: str = address
        self.rssi: int = rssi

class ChessupBLE:
    FileHeaderSize = 7
    PacketHeaderSize = 2
    ImageHeaderSize = 8
    
    NordicService   = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    NordicRXChar    = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
    NordicTXChar    = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    BgCmdScan       = "Scan"
    BgCmdConnect    = "Connect"
    BgCmdDisconnect = "Disconnect"
    BgCmdStop       = "Stop"
    BgCmdScreenshot = "Screenshot"

    BgEvtBoards     = "Boards"
    BgEvtConnected  = "Connected"
    BgEvtScreenshot = "Screenshot"
    BgEvtProgress   = "Progress"

    CUCmdScreenshot = b'\xCA'

    def __init__(self):
        # Addresses of the found boards
        self.discoveredBoards: list[Board] = []

        self.connected = False
        self.connecting = False
        self.disconnecting = False
        self.scanning = False
        self.selectedAdapter: str | None = None
        self.selectedBoard: Board | None = None
        self.currentFileData = None
        self.images: list[png.Image] = []

        self.boardsUpdatedListeners = []
        self.imageReceivedListeners = []
        self.connectionStatusListeners = []
        self.transferProgressListeners = []

        freeze_support()

        # Background task
        self.fgPipe, self.bgPipe = Pipe()
        self.bgProcess = Process(target=self.bgTask)

        # Start the background task
        self.bgProcess.start()

    def finish(self):
        self.fgPipe.send( (ChessupBLE.BgCmdStop, ()) )
        self.bgProcess.join()

    def registerBoardsUpdatedListener(self, listener):
        self.boardsUpdatedListeners.append(listener)

    def registerImageReceivedListener(self, listener):
        self.imageReceivedListeners.append(listener)

    def registerConnectionStatusListener(self, listener):
        self.connectionStatusListeners.append(listener)

    def registerTransferProgressListener(self, listener):
        self.transferProgressListeners.append(listener)

    def isConnected(self):
        return self.connected

    def isConnecting(self):
        return self.connecting

    def isDisconnecting(self):
        return self.disconnecting

    def isScanning(self):
        return self.scanning

    def update(self):
        try:
            while self.fgPipe.poll():
                event, args = self.fgPipe.recv()

                match event:
                    case ChessupBLE.BgEvtBoards:
                        (self.discoveredBoards,) = args
                        self.scanning = False
                        for l in self.boardsUpdatedListeners:
                            l(self.getBoards())

                    case ChessupBLE.BgEvtConnected:
                        isConnected = args[0]
                        statusMessage = args[1]
                        self.connected = isConnected
                        self.connecting = False
                        self.disconnecting = False

                        for l in self.connectionStatusListeners:
                            l(isConnected, statusMessage)

                    case ChessupBLE.BgEvtScreenshot:
                        pngData = args[0]

                        for l in self.imageReceivedListeners:
                            l(pngData)

                    case ChessupBLE.BgEvtProgress:
                        progress = args[0]

                        for l in self.transferProgressListeners:
                            l(progress)

                    case _:
                        print(f"Error: Unknown background event: {event[0]}")

        except Exception as e:
            print(f"Error in BLE update: {e}")
            traceback.print_exc()

    def getAdapters(self):
        return [(a.identifier(), a.address()) for a in Adapter.get_adapters()]

    def getBoards(self):
        return self.discoveredBoards[:]

    def selectAdapter(self, address):
        self.selectedAdapter = address
        print(f"Selected adapter {self.selectedAdapter}")

    def selectBoard(self, address):
        self.selectedBoard = next((b for b in self.discoveredBoards if b.address == address), None)
        if self.selectedBoard is not None:
            print(f"Selected board {self.selectedBoard.address}")

    def scanBoards(self, scanTimeMs=5000):
        if self.selectedAdapter is None:
            print(f"Can't start scan; no adapter selected")
            return

        self.fgPipe.send( (ChessupBLE.BgCmdScan, (self.selectedAdapter, scanTimeMs,)) )
        self.scanning = True

    def connect(self):
        self.fgPipe.send( (ChessupBLE.BgCmdConnect, (self.selectedBoard,)) )
        self.connecting = True

    def bgConnect(self, board: Board):
        targetBoard = next((b for b in self.bgBoards if b.address() == board.address), None)
        if targetBoard is None:
            print(f"Can't connect: unknown peripheral {board.address}")
            return

        try:
            targetBoard.connect()
            self.bgPipe.send( (ChessupBLE.BgEvtConnected, (True, "Connected")) )
            self.bgConnectedBoard = targetBoard

            targetBoard.notify(ChessupBLE.NordicService, ChessupBLE.NordicTXChar, self.bgOnReceiveBLE);

        except Exception as e:
            self.bgPipe.send( (ChessupBLE.BgEvtConnected, (False, f"Connection Error: {e}")) )
            traceback.print_exc()
            return False

    def disconnect(self):
        if (self.isConnected):
            self.fgPipe.send( (ChessupBLE.BgCmdDisconnect, ()) )
            self.disconnecting = True

    def bgDisconnect(self):
        if self.bgConnectedBoard is None:
            return

        try:
            self.bgConnectedBoard.disconnect()
            self.bgConnectedBoard = None
            self.bgPipe.send( (ChessupBLE.BgEvtConnected, (False, "Not connected")) )
        except Exception:
            self.bgPipe.send( (ChessupBLE.BgEvtConnected, (False, "Error disconnecting")) )
            traceback.print_exc()
            pass

    def bgSendBLE(self, data):
        if self.bgConnectedBoard is None:
            return False
        try:
            self.bgConnectedBoard.write_request(ChessupBLE.NordicService, ChessupBLE.NordicRXChar, data);
            return True
        except Exception:
            traceback.print_exc()
            return False

    def bgOnReceiveBLE(self, data):
        match data[0]:
            case 0xB2:
                print("Got board info")

            case 0xf4:
                self.bgOnReceiveFileData(data)
            case _:
                pass

    def requestScreenshot(self):
        self.fgPipe.send( (ChessupBLE.BgCmdScreenshot, ()) )

    def bgStartScreenshot(self):
        self.bgSendBLE(ChessupBLE.CUCmdScreenshot)

    def bgOnReceiveFileData(self, data):
        if len(data) < ChessupBLE.PacketHeaderSize:
            print("Error: File packet too small")
            return

        expectedFileSize = 360 * 240 * 2

        fileId = data[1]

        if fileId not in self.bgFileMap:
            if len(data) < ChessupBLE.FileHeaderSize:
                print("Error: Initial file packet too small")
                return

            self.bgFileMap[fileId] = BLEFile()
            self.bgFileMap[fileId].type = data[2]
            (self.bgFileMap[fileId].crc,) = struct.unpack("<I", data[2:6])
            self.bgFileMap[fileId].data = data[ChessupBLE.FileHeaderSize:]

        elif len(data) > ChessupBLE.PacketHeaderSize:
            self.bgFileMap[fileId].data += data[ChessupBLE.PacketHeaderSize:]
            received = len(self.bgFileMap[fileId].data)
            progress = min(received / expectedFileSize, 1.0)
            self.bgPipe.send( (ChessupBLE.BgEvtProgress, (progress,)) )

        else:
            self.bgPipe.send( (ChessupBLE.BgEvtProgress, (1.0,)) )
            bleFile = self.bgFileMap.pop(fileId)
            self.bgHandleBLEFile(bleFile)

    def bgHandleBLEFile(self, file: BLEFile):
        (imageType,) = struct.unpack('<h', file.data[0:2])
        match imageType:
            case 0:
                self.bgHandleRaw565(file.data[:])
            case _:
                print(f"Error: Unknown image type {imageType}")

    def bgConv565(self, data):
        (rgb565val,) = struct.unpack(">h", data)
        red   = ((rgb565val & 0xF800) >> 11) << 3
        green = ((rgb565val & 0x07E0) >>  5) << 2
        blue  = ((rgb565val & 0x001F) >>  0) << 3
        return (red, green, blue)

    def bgHandleRaw565(self, data):
        format, height, width, bpp = struct.unpack('<hhhh', data[0:ChessupBLE.ImageHeaderSize])
        if bpp != 16:
            print("Error: 565 data must have 16 bits per pixel")
            return

        imageSize = height * width * 2
        colorData = data[ChessupBLE.ImageHeaderSize:]

        if len(colorData) < imageSize:
            print("Error: Payload too small for header image size")
            return

        imageData=[]

        idx = 0
        for _ in range(height):
            thisRow = []
            for _ in range(width):
                thisRow += self.bgConv565(colorData[idx:idx+2])
                idx += 2;
            imageData.append(thisRow)

        writer = png.Writer(width, height, bitdepth=8, greyscale=False);
        buf = BytesIO()
        writer.write(buf, imageData)

        self.bgPipe.send( (ChessupBLE.BgEvtScreenshot, (buf.getvalue(),)) )
        buf.close()

    def getImages(self):
        return self.images

    def bgTask(self):
        # Ignore SIGINT; main thread will handle it
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # Initialization
        self.bgScanning = False
        self.bgConnectedBoard: Peripheral | None = None
        self.bgFileMap: dict[int, BLEFile] = {}
        self.bgBoards: list[Peripheral] = []

        running = True
        while running:
            if self.bgPipe.poll(timeout=1.0):
                cmd, args = self.bgPipe.recv()

                match cmd:
                    case ChessupBLE.BgCmdScan:
                        self.bgScanBoards(*args)

                    case ChessupBLE.BgCmdConnect:
                        self.bgConnect(*args)

                    case ChessupBLE.BgCmdDisconnect:
                        self.bgDisconnect(*args)

                    case ChessupBLE.BgCmdStop:
                        running = False

                    case ChessupBLE.BgCmdScreenshot:
                        self.bgStartScreenshot(*args)
                        
                    case _:
                        print(f"Error: Unknown BG command: {cmd}")

        self.bgDisconnect()

    def bgScanBoards(self, adapterAddr, scanTimeMs):
        if self.bgScanning:
            print(f"Already scanning")
            return

        adapters = [a for a in Adapter.get_adapters() if a.address() == adapterAddr]
        if len(adapters) == 0:
            print(f"Unknown adapter {adapterAddr}")
            return

        self.adapter = adapters[0]

        self.adapter.set_callback_on_scan_start(self.bgOnScanStart)
        self.adapter.set_callback_on_scan_stop(self.bgOnScanEnd)
        self.adapter.set_callback_on_scan_found(self.bgOnPeripheralFound)

        self.adapter.scan_for(scanTimeMs)

    def bgOnScanStart(self):
        print(f"Scan started")
        self.bgScanning = True
        self.bgBoards = []

    def bgOnPeripheralFound(self, p: Peripheral):
        print(f"Found peripheral {p.identifier()} [{p.address()}]")
        if p.identifier() == "ChessUp":
            self.bgBoards.append(p)

    def bgOnScanEnd(self):
        print(f"Scan finished")
        self.bgScanning = False
        discoveredBoards = [Board(b.address(), b.rssi()) for b in self.bgBoards]
        self.bgPipe.send( (ChessupBLE.BgEvtBoards, (discoveredBoards,)) )
