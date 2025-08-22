# Search and replace these in all your Python files:

EMOJI_TO_ASCII = {
    "🚀": "[START]",
    "📱": "[CAM]", 
    "📋": "[CONFIG]",
    "✅": "[OK]",
    "❌": "X",
    "⚠️": "[WARN]",
    "🔗": "[CONNECT]",
    "🔧": "[SETUP]",
    "🧹": "[CLEAN]",
    "📶": "[WIFI]",
    "📡": "[WPA]",
    "⏳": "[WAIT]",
    "🌐": "[DHCP]",
    "🔍": "[CHECK]",
    "🎯": "[MENU]",
    "🎮": "[CTRL]",
    "🎬": "[REC]",
    "📸": "[PHOTO]",
    "🔴": "[REC]",
    "⏹️": "[STOP]",
    "📄": "[CONFIG]",
    "💾": "[SAVE]",
    "🔌": "[DISC]",
    "👋": "[EXIT]",
    "💡": "[HELP]",
    "🛣️": "[ROUTE]",
    "📊": "[STATUS]",
    "🔑": "[AUTH]",
    "🗑️": "[DEL]",
    "📍": "[IP]"
}

# Use this Python script to convert your files:
import re

def convert_file_to_ascii(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for emoji, ascii_equiv in EMOJI_TO_ASCII.items():
        content = content.replace(emoji, ascii_equiv)
    
    with open(filename + '_ascii', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Converted {filename} to {filename}_ascii")

# Convert your files:
convert_file_to_ascii('dual_wifi_manager.py')
# convert_file_to_ascii('main.py')
# convert_file_to_ascii('wifi_camera_controller.py')
# convert_file_to_ascii('single_gopro_controller.py')