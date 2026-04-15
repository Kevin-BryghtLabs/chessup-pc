import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

class ChessupUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="Chessup UI")

        self.button = Gtk.Button(label="Click")
        self.button.connect("clicked", self.on_button_clicked)
