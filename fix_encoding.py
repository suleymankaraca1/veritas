import os, glob

files = glob.glob(r"C:\Users\suley\Desktop\veritas\agents\*.py")
fixed = 0
for f in files:
    try:
        with open(f, "rb") as fp:
            raw = fp.read()
        # Strip BOM if present
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        # Now raw is the corrupted UTF-8 data
        # Decode as UTF-8 to get the mangled Unicode string
        content = raw.decode("utf-8")
        # Re-encode as latin-1 to get original bytes, then decode as UTF-8
        try:
            restored = content.encode("latin-1").decode("utf-8")
        except Exception:
            # If latin-1 fails, content might already be correct - just strip BOM
            restored = content
        # Write back as UTF-8 without BOM
        with open(f, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(restored)
        fixed += 1
        print(f"Fixed: {os.path.basename(f)}")
    except Exception as e:
        print(f"Error {os.path.basename(f)}: {e}")
print(f"Total fixed: {fixed}")
