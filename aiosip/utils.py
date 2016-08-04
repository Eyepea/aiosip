import random
import string

EOL = '\r\n'

def gen_str(length=10, letters=string.ascii_letters+string.digits):
    return "".join([random.choice(letters) for n in range(length)])


def gen_branch(length=10, letters=string.ascii_letters+string.digits):
    return "".join(("z9hG4bK", gen_str(length=length, letters=letters)))
