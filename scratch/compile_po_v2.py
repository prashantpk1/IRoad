
import struct
import array
import re

def msgfmt(po_path, mo_path):
    # This is a more complete msgfmt implementation
    MESSAGES = {}
    
    with open(po_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove comments
    content = re.sub(r'^#.*$', '', content, flags=re.MULTILINE)
    
    # Find all msgid/msgstr pairs
    # Supports multi-line and escaped quotes
    entries = re.findall(r'msgid\s+((?:"(?:\\.|[^"])*"\s*)+)\s*msgstr\s+((?:"(?:\\.|[^"])*"\s*)+)', content)
    
    for id_str, str_str in entries:
        def parse_str(s):
            # Combine multi-line strings
            parts = re.findall(r'"((?:\\.|[^"])*)"', s)
            combined = "".join(parts)
            # Handle escapes
            return combined.encode('utf-8').decode('unicode_escape')
        
        try:
            msgid = parse_str(id_str)
            msgstr = parse_str(str_str)
            if msgid and msgstr:
                MESSAGES[msgid] = msgstr
        except Exception as e:
            print(f"Error parsing entry: {id_str} -> {e}")

    keys = sorted(MESSAGES.keys())
    num_entries = len(keys)
    
    offsets = []
    ids = b''
    strs = b''
    
    for k in keys:
        v = MESSAGES[k].encode('utf-8')
        kb = k.encode('utf-8')
        offsets.append((len(ids), len(kb), len(strs), len(v)))
        ids += kb + b'\0'
        strs += v + b'\0'
    
    key_start = 7 * 4 + 16 * num_entries
    val_start = key_start + len(ids)
    
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, key_start + o1]
        voffsets += [l2, val_start + o2]
        
    # Magic number: 0x950412de
    # Version: 0
    # Number of messages
    # Offset of msgid table
    # Offset of msgstr table
    # Size/Offset of hash table (we'll set to 0/0)
    magic = 0x950412de
    header = struct.pack('<Iiiiiii',
                         magic, 
                         0, 
                         num_entries,
                         7 * 4, 
                         7 * 4 + 8 * num_entries,
                         0, 0)
    
    data = header + array.array('i', koffsets).tobytes() + array.array('i', voffsets).tobytes() + ids + strs
    
    with open(mo_path, 'wb') as f:
        f.write(data)
    print(f"Successfully compiled {num_entries} messages.")

if __name__ == "__main__":
    po = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.po"
    mo = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.mo"
    msgfmt(po, mo)
