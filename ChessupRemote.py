#!/usr/bin/env python

import gi
import os
import sys
import signal

# Must come before the `from gi.repository` imports
gi.require_version("Gtk", "3.0")

from ChessupBLE import ChessupBLE, Board
from datetime import datetime
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

def timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

class ChessupUI():
    def __init__(self):
        self.application = Gtk.Application()
        self.application.connect("activate", self.onActivate)

        self.adapterMap = {}
        self.boardMap = {}

        self.pngData: bytes | None = None

        self.ble = ChessupBLE()
        self.ble.registerBoardsUpdatedListener(self.onBLEBoardsUpdated)
        self.ble.registerConnectionStatusListener(self.onBLEConnectionStatus)
        self.ble.registerTransferProgressListener(self.onBLETransferProgress)
        self.ble.registerImageReceivedListener(self.onBLEImageReceived)

        self.saveDirectory = os.getcwd()

        self.currentPixbuf: GdkPixbuf | None = None

    def getResourceFile(self, relativeFile):
        try:
            # This is set by PyInstaller when deployed
            basePath = sys._MEIPASS
        except AttributeError:
            # Use this directory for development
            basePath = os.path.abspath(".")

        return os.path.join(basePath, relativeFile)

    def onActivate(self, application):
        self.builder = Gtk.Builder()
        self.builder.add_from_file(self.getResourceFile("ChessupRemote.glade"))

        self.window = self.builder.get_object("ChessupApplication")
        self.adapterComboBox: Gtk.ComboBoxText = self.builder.get_object("AdapterComboBox")
        self.boardComboBox: Gtk.ComboBoxText = self.builder.get_object("BoardComboBox")
        self.connectionStatusLabel: Gtk.Label = self.builder.get_object("ConnectionStatusLabel")
        self.screenshotImage: Gtk.Image = self.builder.get_object("ScreenshotImage")
        self.transferProgress: Gtk.ProgressBar = self.builder.get_object("TransferProgress")
        self.connectButton: Gtk.Button = self.builder.get_object("ConnectButton")
        self.disconnectButton: Gtk.Button = self.builder.get_object("DisconnectButton")
        self.captureButton: Gtk.Button = self.builder.get_object("CaptureButton")
        self.saveButton: Gtk.Button = self.builder.get_object("SaveButton")
        self.copyButton: Gtk.Button = self.builder.get_object("CopyButton")
        self.scanButton: Gtk.Button = self.builder.get_object("ScanButton")
        self.autosaveCheckButton: Gtk.CheckButton = self.builder.get_object("AutosaveCheckButton")
        self.autocopyCheckButton: Gtk.CheckButton = self.builder.get_object("AutocopyCheckButton")
        self.autosaveDirectoryLabel: Gtk.CheckButton = self.builder.get_object("AutosaveDirectoryLabel")

        self.normalScanButtonText = self.scanButton.get_label()
        self.normalConnectButtonText = self.connectButton.get_label()

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

    def onBLEBoardsUpdated(self, boards: list[Board]):
        # On a re-scan; store the previous selection so we can keep it selected
        activeItem = self.boardComboBox.get_active_text()
        newActiveIndex = -1

        self.boardMap = {}
        self.boardComboBox.remove_all()

        boards.sort(key=lambda b: b.rssi, reverse=True)

        for e, b in enumerate(boards):
            addrLen = len(b.address)

            label = f"{b.address} (Signal: {b.rssi})"

            if activeItem is not None and label[:addrLen] == activeItem[:addrLen]:
                newActiveIndex = e

            # Map the text in the combo box to the adapter address
            #   so we can find it when it is clicked.
            self.boardMap[label] = b.address
            self.boardComboBox.append_text(label)

        if newActiveIndex >= 0:
            self.boardComboBox.set_active(newActiveIndex)

        self.setButtonsState()

    def setButtonsState(self):
        isConnected = self.ble.isConnected()
        isConnecting = self.ble.isConnecting()
        isScanning = self.ble.isScanning()

        isBusy = isConnecting or isScanning
        canConnect = not isBusy and not isConnected and self.boardComboBox.get_active_text() is not None
        haveScreenshot = self.pngData is not None and self.currentPixbuf is not None

        self.connectButton.set_sensitive(canConnect)
        self.disconnectButton.set_sensitive(isConnected)
        self.captureButton.set_sensitive(isConnected)
        self.scanButton.set_sensitive(not isBusy)
        self.saveButton.set_sensitive(haveScreenshot)
        self.copyButton.set_sensitive(haveScreenshot)
        self.adapterComboBox.set_sensitive(not isConnected and not isBusy)
        self.boardComboBox.set_sensitive(not isConnected and not isBusy)

        self.scanButton.set_label("Scanning..." if isScanning else self.normalScanButtonText)
        self.connectButton.set_label("Connecting..." if isConnecting else self.normalConnectButtonText)
        self.autosaveDirectoryLabel.set_label(self.saveDirectory)

    def onBLEConnectionStatus(self, isConnected, statusMessage):
        self.connectionStatusLabel.set_text(statusMessage)
        self.setButtonsState()

    def onBLETransferProgress(self, progress):
        self.transferProgress.set_fraction(progress)

    def saveImage(self, filename=None):
        if self.pngData is None:
            return

        if filename is None:
            filename = "CUScreenshot-" + timestamp() + ".png"
            filename = os.path.join(self.saveDirectory, filename)

        with open(filename, "wb") as f:
            f.write(self.pngData)

    def copyImage(self):
        if self.currentPixbuf is not None:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_image(self.currentPixbuf)

    def onBLEImageReceived(self, pngData):
        self.pngData = pngData
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(pngData)
        loader.close()
        self.currentPixbuf = loader.get_pixbuf()

        self.screenshotImage.set_from_pixbuf(self.currentPixbuf)

        if self.autosaveCheckButton.get_active():
            self.saveImage()

        if self.autocopyCheckButton.get_active():
            self.copyImage()

        self.setButtonsState()

    def onCaptureButtonClicked(self, widget):
        self.ble.requestScreenshot()

    def onCopyButtonClicked(self, widget):
        self.copyImage()

    def onScanButtonClicked(self, widget):
        self.ble.scanBoards()
        self.setButtonsState()

    def onSaveButtonClicked(self, widget):
        saveDialog = Gtk.FileChooserDialog(
                title="Save Screenshot",
                parent=self.window,
                action=Gtk.FileChooserAction.SAVE,
                buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
            )
        saveDialog.set_current_folder(self.saveDirectory)

        response = saveDialog.run()
        if response == Gtk.ResponseType.OK:
            filename = saveDialog.get_filename()
            # If the user selected a new directory, remember it
            self.saveDirectory = os.path.dirname(filename)
            if len(filename) < 4 or filename[-4:].lower() != ".png":
                filename += ".png"
            self.saveImage(filename)

        saveDialog.destroy()

    def onAutosaveDirectorySelectButtonClicked(self, widget):
        saveDialog = Gtk.FileChooserDialog(
                title="Auto-save Directory",
                parent=self.window,
                action=Gtk.FileChooserAction.SELECT_FOLDER,
                buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
            )
        saveDialog.set_current_folder(self.saveDirectory)

        response = saveDialog.run()
        if response == Gtk.ResponseType.OK:
            saveDirectory = saveDialog.get_filename()
            self.saveDirectory = saveDirectory

        saveDialog.destroy()
        self.setButtonsState()

    def onAdapterComboBoxChanged(self, widget):
        label = widget.get_active_text()
        if label in self.adapterMap:
            self.ble.selectAdapter(self.adapterMap[label])

    def onBoardComboBoxChanged(self, widget):
        label = widget.get_active_text()
        if label in self.boardMap:
            self.ble.selectBoard(self.boardMap[label])
            self.setButtonsState()

    def onConnectButtonClicked(self, widget):
        self.ble.connect()
        self.setButtonsState()

    def onDisconnectButtonClicked(self, widget):
        self.ble.disconnect()
        self.setButtonsState()

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

if __name__ == "__main__":
    c = ChessupUI()
    c.run(sys.argv)
