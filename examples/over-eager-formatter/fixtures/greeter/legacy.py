def parse(line):
    key, _, value = line.partition("=")
    return key.strip(), value.strip()
