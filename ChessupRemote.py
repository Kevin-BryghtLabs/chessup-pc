#!/usr/bin/env python

import gi
import os
import sys
import signal

# Must come before the `from gi.repository` imports
gi.require_version("Gtk", "3.0")

from ChessupBLE import ChessupBLE
from datetime import datetime
from gi.repository import Gtk, GLib, GdkPixbuf

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

    def onActivate(self, application):
        self.builder = Gtk.Builder()
        self.builder.add_from_file("ChessupRemote.glade")

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
        self.autosaveCheckButton: Gtk.CheckButton = self.builder.get_object("AutosaveCheckButton")

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
        self.adapterComboBox.set_sensitive(not isConnected)
        self.boardComboBox.set_sensitive(not isConnected)

    def onBLEConnectionStatus(self, isConnected, statusMessage):
        self.connectionStatusLabel.set_text(statusMessage)
        self.setButtonsState()

    def onBLETransferProgress(self, progress):
        self.transferProgress.set_fraction(progress)

    def saveImage(self, filename=None):
        print(f"Filename: {filename}")
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
