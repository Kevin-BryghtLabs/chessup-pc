#!/usr/bin/env python

import gi
import sys
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf
from cuctl import ChessupBLE
import signal
from datetime import datetime

def timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

class ChessupUI():
    def __init__(self):
        self.application = Gtk.Application()
        self.application.connect("activate", self.onActivate)

        #self.captureButton = self.builder.get_object("CaptureButton")
        #self.scanButton = self.builder.get_object("ScanButton")

        self.adapterMap = {}
        self.boardMap = {}

        self.haveScreenshot = False
        self.pngData: bytes | None = None

        self.ble = ChessupBLE()
        self.ble.registerBoardsUpdatedListener(self.onBLEBoardsUpdated)
        self.ble.registerConnectionStatusListener(self.onBLEConnectionStatus)
        self.ble.registerTransferProgressListener(self.onBLETransferProgress)
        self.ble.registerImageReceivedListener(self.onBLEImageReceived)

    def onActivate(self, application):
        self.builder = Gtk.Builder()
        self.builder.add_from_file("cucll.ui")

        self.window = self.builder.get_object("ChessupApplication")
        self.adapterComboBox: Gtk.ComboBoxText = self.builder.get_object("AdapterComboBox")
        self.boardComboBox: Gtk.ComboBoxText = self.builder.get_object("BoardComboBox")
        self.connectionStatusLabel: Gtk.Label = self.builder.get_object("ConnectionStatusLabel")
        self.screenshotImage: Gtk.Image = self.builder.get_object("ScreenshotImage")
        self.transferProgress: Gtk.ProgressBar = self.builder.get_object("TransferProgress")
        self.connectButton: Gtk.ProgressBar = self.builder.get_object("ConnectButton")
        self.disconnectButton: Gtk.ProgressBar = self.builder.get_object("DisconnectButton")
        self.captureButton: Gtk.ProgressBar = self.builder.get_object("CaptureButton")
        self.saveButton: Gtk.ProgressBar = self.builder.get_object("SaveButton")
        self.autosaveCheckButton: Gtk.ProgressBar = self.builder.get_object("AutosaveCheckButton")

        self.builder.connect_signals(self)

        self.window.set_application(application)
        self.window.show_all()

        self.setAdapterOptions(self.ble.getAdapters())

        self.setButtonsState()

        GLib.timeout_add(100, self.updateBle)

    def setAdapterOptions(self, adapters):
        count = 0

        self.adapterMap = {}
        self.adapterComboBox.remove_all()

        for a in adapters:
            label = a[0] + ": " + a[1];

            # Map the text in the combo box to the adapter address
            #   so we can find it when it is clicked
            self.adapterMap[label] = a[1]
            self.adapterComboBox.append_text(label)
            count += 1

        # Automatically select the first adapter
        if count > 0:
            self.adapterComboBox.set_active(0)


    def onBLEBoardsUpdated(self, boards):
        print("Boards Updated Signal")
        # On a re-scan; store the previous selection so we can keep it selected
        activeItem = self.boardComboBox.get_active_text()
        newActiveIndex = -1

        self.boardMap = {}
        self.boardComboBox.remove_all()
        for e, b in enumerate(boards):
            label = b

            if label == activeItem:
                newActiveIndex = e

            # Map the text in the combo box to the adapter address
            #   so we can find it when it is clicked.  (Right now
            #   they are the same, but allow change in the future)
            self.boardMap[label] = b
            self.boardComboBox.append_text(label)

        if newActiveIndex >= 0:
            self.boardComboBox.set_active(newActiveIndex)

    def setButtonsState(self):
        isConnected = self.ble.isConnected()
        canConnect = not isConnected and self.boardComboBox.get_active_text() is not None

        self.connectButton.set_sensitive(canConnect)
        self.disconnectButton.set_sensitive(isConnected)
        self.captureButton.set_sensitive(isConnected)
        self.saveButton.set_sensitive(self.haveScreenshot)
        self.boardComboBox.set_sensitive(not isConnected)

    def onBLEConnectionStatus(self, isConnected, statusMessage):
        self.isConnected = isConnected
        self.connectionStatusLabel.set_text(statusMessage)
        self.setButtonsState()

    def onBLETransferProgress(self, progress):
        self.transferProgress.set_fraction(progress)

    def saveImage(self, filename=None):
        if self.pngData is None:
            return

        if filename is None:
            filename = "CUScreenshot-" + timestamp() + ".png"

        with open(filename, "wb") as f:
            f.write(self.pngData)

    def onBLEImageReceived(self, pngData):
        self.pngData = pngData
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(pngData)
        loader.close()

        self.screenshotImage.set_from_pixbuf(loader.get_pixbuf())

        if self.autosaveCheckButton.get_active():
            self.saveImage()

        self.haveScreenshot = True
        self.setButtonsState()

    def onCaptureButtonClicked(self, widget):
        self.ble.requestScreenshot()

    def onScanButtonClicked(self, widget):
        self.ble.scanBoards()

    def onSaveButtonClicked(self, widget):
        self.saveImage()

    def onAdapterComboBoxChanged(self, widget):
        label = widget.get_active_text()
        print(f"Adapter: {label}")
        if label in self.adapterMap:
            self.ble.selectAdapter(self.adapterMap[label])

    def onBoardComboBoxChanged(self, widget):
        label = widget.get_active_text()
        print(f"Board: {label}")
        if label in self.boardMap:
            self.ble.selectBoard(self.boardMap[label])
            self.setButtonsState()

    def onConnectButtonClicked(self, widget):
        self.ble.connect()

    def onDisconnectButtonClicked(self, widget):
        self.ble.disconnect()

    def onWindowDestroyed(self, widget):
        self.ble.finish()
        self.application.quit()

    def updateBle(self):
        self.ble.update()
        return True

    def handleSIGINT(self, signum, frame):
        print("Received SIGINT, shutting down...")
        self.ble.finish()
        GLib.idle_add(self.application.quit)

    def run(self, argv):
        try:
            signal.signal(signal.SIGINT, self.handleSIGINT)

            exit_status = self.application.run(argv)
            sys.exit(exit_status)

        except Exception:
            pass

c = ChessupUI()
c.run(sys.argv)
