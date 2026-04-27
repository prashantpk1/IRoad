
import struct
import array
import re

def msgfmt(po_path, mo_path):
    MESSAGES = {}
    
    with open(po_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Simple parsing: find msgid and msgstr pairs
    # This handles multi-line strings
    entries = re.findall(r'msgid\s+((?:".*?"\s*)+)\s*msgstr\s+((?:".*?"\s*)+)', content, re.DOTALL)
    
    for id_data, str_data in entries:
        def clean(s):
            parts = re.findall(r'"(.*?)"', s, re.DOTALL)
            combined = "".join(parts)
            # Unescape characters
            combined = combined.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
            return combined

        msgid = clean(id_data)
        msgstr = clean(str_data)
        
        # Don't skip empty msgid as it's the header
        MESSAGES[msgid] = msgstr

    keys = sorted(MESSAGES.keys())
    num_entries = len(keys)
    
    ids = b''
    strs = b''
    offsets = []
    
    for k in keys:
        id_bytes = k.encode('utf-8')
        str_bytes = MESSAGES[k].encode('utf-8')
        offsets.append((len(ids), len(id_bytes), len(strs), len(str_bytes)))
        ids += id_bytes + b'\0'
        strs += str_bytes + b'\0'
        
    keystart = 7 * 4 + 16 * num_entries
    valstart = keystart + len(ids)
    
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, keystart + o1]
        voffsets += [l2, valstart + o2]
        
    header = struct.pack('<Iiiiiii',
                         0x950412de, 0, num_entries,
                         7 * 4, 7 * 4 + 8 * num_entries,
                         0, 0)
    
    with open(mo_path, 'wb') as f:
        f.write(header)
        f.write(array.array('I', koffsets).tobytes())
        f.write(array.array('I', voffsets).tobytes())
        f.write(ids)
        f.write(strs)

    print(f"Compiled {num_entries} messages to {mo_path}")

if __name__ == "__main__":
    po = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.po"
    mo = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.mo"
    msgfmt(po, mo)
