#!/usr/bin/env python
# author: Iraj Jelodari

import datetime
import codecs
import re
from typing import Union

# Standard color constants
COLORS = {
    'RED': '#FF003B',
    'BLUE': '#00ADFF',
    'GREEN': '#B4FF00',
    'WHITE': '#FFFFFF',
    'YELLOW': '#FFEB00',
    'CYAN': '#00FFFF',
    'MAGENTA': '#FF00FF',
    'ORANGE': '#FFA500',
    'PURPLE': '#800080',
    'PINK': '#FFC0CB'
}

TIME_PATTERN = r'\d{1,2}:\d{1,2}:\d{1,2},\d{1,5} --> \d{1,2}:\d{1,2}:\d{1,2},\d{1,5}\r\n'

def normalize_color(color: Union[str, None]) -> Union[str, None]:
    """
    Normalize color input to a valid hex color code.
    Accepts:
    - Named colors from COLORS dict
    - Hex codes with or without #
    - RGB tuples as string "(r,g,b)"
    """
    if not color:
        return None
        
    # Strip whitespace and convert to uppercase for comparison
    color = color.strip().upper()
    
    # If it's a predefined color name
    if color in COLORS:
        return COLORS[color]
        
    # If it's already a valid hex code with #
    if re.match(r'^#[0-9A-F]{6}$', color):
        return color
        
    # If it's a hex code without #
    if re.match(r'^[0-9A-F]{6}$', color):
        return f'#{color}'
        
    # If it's an RGB tuple string
    rgb_match = re.match(r'^\((\d+),\s*(\d+),\s*(\d+)\)$', color)
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        if all(0 <= x <= 255 for x in (r, g, b)):
            return f'#{r:02x}{g:02x}{b:02x}'.upper()
    
    # If no valid format is found, return default white
    return COLORS['WHITE']

class Merger():
    """
    SRT Merger allows you to merge subtitle files, no matter what language
    are the subtitles encoded in. The result of this merge will be a new subtitle
    file which will display subtitles from each merged file.
    """

    def __init__(self, output_path=".", output_name='subtitle_name.srt', output_encoding='utf-8'):
        self.timestamps = []
        self.subtitles = []
        self.lines = []
        self.output_path = output_path
        self.output_name = output_name
        self.output_encoding = output_encoding
        self.font_sizes = []  # Store font sizes for each subtitle

    def _insert_bom(self, content, encoding):
        encoding = encoding.replace('-', '')\
            .replace('_', '')\
            .replace(' ', '')\
            .upper()
        if encoding in ['UTF64LE', 'UTF16', 'UTF16LE']:
            return codecs.BOM + content
        if encoding in ['UTF8']:
            return codecs.BOM_UTF8 + content
        if encoding in ['UTF32LE']:
            return codecs.BOM_UTF32_LE + content
        if encoding in ['UTF64BE']:
            return codecs.BOM_UTF64_BE + content
        if encoding in ['UTF16BE']:
            return codecs.BOM_UTF32_BE + content
        if encoding in ['UTF32BE']:
            return codecs.BOM_UTF32_BE + content
        if encoding in ['UTF32']:
            return codecs.BOM_UTF32 + content
        return content

    def _set_subtitle_style(self, subtitle, color=None, size=None):
        """
        Set color and size for subtitle. Color can be:
        - Named color from COLORS dict
        - Hex code (with or without #)
        - RGB tuple as string "(r,g,b)"
        Size should be a number representing the font size.
        """
        # Remove any existing font tags
        subtitle = re.sub(r'<font[^>]*>(.*?)</font>', r'\1', subtitle)
        
        # Normalize color
        color = normalize_color(color)
        
        # Build style attributes
        style_attrs = []
        if color:
            style_attrs.append(f'color="{color}"')
        if size:
            style_attrs.append(f'size="{size}"')
        
        style = ' '.join(style_attrs)
        return f'<font {style}>{subtitle}</font>' if style else subtitle

    def _put_subtitle_top(self, subtitle):
        """
        Put the subtitle at the top of the screen with adjusted positioning
        """
        # Remove any existing alignment tags
        subtitle = re.sub(r'{\\\an\d}', '', subtitle)
        # Use \an8 for top position with adjusted vertical spacing
        return '{\\an8}' + subtitle

    def _split_dialogs(self, dialogs, subtitle, color=None, size=None, top=False):
        for dialog in dialogs:
            if dialog.startswith('\r\n'):
                dialog = dialog.replace('\r\n', '', 1)
            if dialog.startswith('\n'):
                dialog = dialog[1:]
            if dialog == '' or dialog == '\n' or dialog.rstrip().lstrip() == '':
                continue
            try:
                if dialog.startswith('\r\n'):
                    dialog = dialog[2:]
                time = dialog.split('\n', 2)[1]  # Get full timestamp line
                timestamp = time.split('-->')[0].strip()  # Get start time
            except Exception as e:
                continue

            try:
                # Parse timestamp for sorting
                timestamp = datetime.datetime.strptime(
                    timestamp, '%H:%M:%S,%f').timestamp()
                
                text_and_time = dialog.split('\n', 1)[1]
                texts = text_and_time.split('\n')[1:]
                text = ""
                for t in texts:
                    text += t + '\n'
                if text == '' or text == '\n':
                    continue
                
                # Apply style
                text = text.rstrip()  # Remove trailing newlines
                if size:
                    text = f'<font face="Gandhi Sans" size="{size}">{text}</font>'
                if color:
                    text = f'<font color="{color}">{text}</font>'
                
                # Apply positioning
                if top:
                    text = '{\\an8}' + text
                
                # Keep the original timestamp line
                text_and_time = f'{time}\n{text}\n'
                
                # Combine with existing dialog for same timestamp
                if timestamp in subtitle['dialogs']:
                    # Add to existing dialog
                    prev_text = subtitle['dialogs'][timestamp].split('\n', 2)[2].strip()
                    text_and_time = f'{time}\n{prev_text}\n{text}\n'
                
                subtitle['dialogs'][timestamp] = text_and_time
                self.timestamps.append(timestamp)
                
            except Exception as e:
                self.logger.error(f"Error processing dialog: {e}")
                continue

    def _encode(self, text):
        codec = self.output_encoding
        try:
            return bytes(text, encoding=codec)
        except Exception as e:
            print('Problem in "%s" to encoing by %s. \nError: %s' %
                  (repr(text), codec, e))
            return b'An error has been occured in encoing by specifed `output_encoding`'

    def add(self, subtitle_address, codec="utf-8", color=COLORS['WHITE'], size=None, top=False):
        """
        Add a subtitle file to be merged.
        
        Args:
            subtitle_address (str): Path to the subtitle file
            codec (str): Character encoding of the subtitle file
            color (str): Color for the subtitle text. Can be:
                        - Named color from COLORS dict
                        - Hex code (with or without #)
                        - RGB tuple as string "(r,g,b)"
            size (int): Font size for the subtitle text
            top (bool): Whether to position the subtitle at the top
        """
        subtitle = {
            'address': subtitle_address,
            'codec': codec,
            'color': color,
            'size': size,
            'dialogs': {}
        }
        with open(subtitle_address, 'r') as file:
            data = file.buffer.read().decode(codec)
            dialogs = re.split('\r\n\r|\n\n', data)
            subtitle['data'] = data
            subtitle['raw_dialogs'] = dialogs
            self._split_dialogs(dialogs, subtitle, color, size, top)
            self.subtitles.append(subtitle)

    def get_output_path(self):
        if self.output_path.endswith('/'):
            return self.output_path + self.output_name
        return self.output_path + '/' + self.output_name

    def merge(self):
        self.lines = []
        self.timestamps = list(set(self.timestamps))
        self.timestamps.sort()
        count = 1
        for t in self.timestamps:
            for sub in self.subtitles:
                if t in sub['dialogs'].keys():
                    line = self._encode(sub['dialogs'][t].replace('\n\n', ''))
                    if count == 1:
                        byteOfCount = self._insert_bom(
                            bytes(str(count), encoding=self.output_encoding),
                            self.output_encoding
                        )
                    else:
                        byteOfCount = '\n'.encode(
                            self.output_encoding) + bytes(str(count), encoding=self.output_encoding)
                    if sub['dialogs'][t].endswith('\n') != True:
                        sub['dialogs'][t] = sub['dialogs'][t] + '\n'
                    dialog = byteOfCount + \
                        '\n'.encode(self.output_encoding) + line
                    self.lines.append(dialog)
                    count += 1
        if self.lines[-1].endswith(b'\x00\n\x00'):
            self.lines[-1] = self.lines[-1][:-3] + b'\x00'
        if self.lines[-1].endswith(b'\n'):
            self.lines[-1] = self.lines[-1][:-1] + b''
        with open(self.get_output_path(), 'w', encoding=self.output_encoding) as output:
            output.buffer.writelines(self.lines)
            print("'%s'" % (output.name), 'created successfully.')


# How to use?
#
# m = Merger(output_name="new.srt")
# m.add('./test_srt/en.srt')
# m.add('./test_srt/fa.srt', color="yellow", codec="cp1256", top=True)
# m.merge()
