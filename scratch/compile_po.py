
import struct
import array

def msgfmt(po_file, mo_file):
    ID = 0x950412de
    VERSION = 0
    
    messages = {}
    with open(po_file, 'rb') as f:
        content = f.read().decode('utf-8')
        
    import re
    # Very basic parser for po files
    entries = re.findall(r'msgid\s+"(.*?)".*?msgstr\s+"(.*?)"', content, re.DOTALL)
    for msgid, msgstr in entries:
        msgid = msgid.replace('"\n"', '').replace('\\n', '\n').replace('\\"', '"')
        msgstr = msgstr.replace('"\n"', '').replace('\\n', '\n').replace('\\"', '"')
        if msgid and msgstr:
            messages[msgid] = msgstr

    keys = sorted(messages.keys())
    offsets = []
    ids = b''
    strs = b''
    
    for k in keys:
        v = messages[k].encode('utf-8')
        k = k.encode('utf-8')
        offsets.append((len(ids), len(k), len(strs), len(v)))
        ids += k + b'\0'
        strs += v + b'\0'
        
    keystart = 7 * 4 + 16 * len(keys)
    valstart = keystart + len(ids)
    
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, keystart + o1]
        voffsets += [l2, valstart + o2]
        
    output = struct.pack('<Iiiiiii',
                         ID, VERSION, len(keys),
                         7 * 4, 7 * 4 + 8 * len(keys),
                         0, 0)
    output += array.array('i', koffsets).tobytes()
    output += array.array('i', voffsets).tobytes()
    output += ids
    output += strs
    
    with open(mo_file, 'wb') as f:
        f.write(output)

if __name__ == "__main__":
    po = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.po"
    mo = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.mo"
    msgfmt(po, mo)
    print(f"Compiled {po} to {mo}")
