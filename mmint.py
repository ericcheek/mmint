#!/usr/bin/python

import json
import re
import copy
import time
from datetime import timedelta, datetime

_commandTable = []
def StackCommand(regex):
    def _command(func):
        def wrapper(blob, **kwargs):
            blob['stack' ] = func(blob['stack'], **kwargs)
            return blob

        _commandTable.append((re.compile(regex), wrapper))
        return wrapper
    
    return _command

def Command(regex):
    def _command(func):
        _commandTable.append((re.compile(regex), func))
        return func
    
    return _command


def matchAndRun(line, blobData):
    for commandRegex, commandFunc in _commandTable:
        match = commandRegex.match(line)
        if match is not None:            
            return commandFunc(copy.deepcopy(blobData), **match.groupdict())
    return blobData

def sync(current, dbfile):
    if current is None:
        try:
            with open(dbfile) as f:
                current = json.loads(f.read())
                # schema transformations
                if type(current) is list:
                    current = {
                        '_schema_version': '1',
                        'stack': current,
                        'snoozed': []
                    }
                    # TODO make backup on schema transform
                    
        except IOError:
            current = {
                '_schema_version': '1',
                'stack': [],
                'snoozed': []
            }
    else:
        with open(dbfile, 'w') as f:
            f.write(json.dumps(current))

    now = datetime.utcnow()

    nowActive = filter(lambda x: datetime.fromtimestamp(x['ttime']) <= now, current['snoozed'])
    current['snoozed'] = filter(lambda x: datetime.fromtimestamp(x['ttime']) > now, current['snoozed'])
    current['stack'].extend(map(lambda x: x['item'], nowActive))
            
    return current


@StackCommand(r"push (?P<value>.*)")
def push(stack, **kwargs):    
    return [kwargs['value']] + stack

@StackCommand(r"pop")
def pop(stack, **kwargs):    
    return stack[1:]

@StackCommand(r"chunk (?P<count>[0-9]+)")
def chunk(stack, **kwargs):
    count = int(kwargs['count'])
    return [stack[:count]] + stack[count:]

@StackCommand(r"expand")
def expand(stack, **kwargs):
    return stack[0] + stack[1:]

@StackCommand(r"mv (?P<src>[0-9]+) (?P<dest>[0-9]+)")
def mv(stack, **kwargs):
    src = int(kwargs['src'])
    dest = int(kwargs['dest'])

    v = stack[src]
    del stack[src]
    stack.insert(dest, v)
    
    return stack

@StackCommand(r"swap ?((?P<src>[0-9]+) (?P<dest>[0-9]+))?")
def swap(stack, **kwargs):
    src = 0 if kwargs['src'] is None else int(kwargs['src'])
    dest = 1 if kwargs['dest'] is None else int(kwargs['dest'])

    v = stack[src]
    stack[src] = stack[dest]
    stack[dest] = v
    
    return stack

@StackCommand(r"cp ?(?P<src>[0-9]+)")
def cp(stack, **kwargs):
    src = 0 if kwargs['src'] is None else int(kwargs['src'])

    return [stack[src]] + stack

@StackCommand(r"rot ?(-n (?P<count>[0-9]+))?")
def rot(stack, **kwargs):
    count = 1 if kwargs['count'] is None else int(kwargs['count'])
    
    return [stack[(i + count) % len(stack)] for i in xrange(len(stack))]

@StackCommand(r"reverse")
def reverse(stack, **kwargs):
    stack.reverse()
    
    return stack

@StackCommand(r"edit ?(--index (?P<index>[0-9]+))? (?P<value>.*)")
def edit(stack, **kwargs):
    index = 0 if kwargs['index'] is None else int(kwargs['index'])
    stack[index] = kwargs['value']
    return stack

@Command(r"apply (?P<index>[0-9]+) (?P<command>.*)")
def apply(blob, **kwargs):
    index = int(kwargs['index'])
    command = kwargs['command']

    stack = blob['stack']
    
    if type(stack[index]) is not list:
        print "Must target lists"
        return stack

    # only used with stack commands
    newSubstack = matchAndRun(command, {'stack': stack[index]})['stack']
    blob['stack'][index] = newSubstack
    return blob

@Command(r"snooze ?(--index (?P<index>[0-9]+))? (?P<multiplier>[0-9]+)(?P<period>[smhDWMQY])")
def snooze(blob, **kwargs):
    index = 0 if kwargs['index'] is None else int(kwargs['index'])

    periodDuration = {
        's': timedelta(seconds=1),
        'm': timedelta(minutes=1),
        'h': timedelta(hours=1),
        'D': timedelta(days=1),
        'W': timedelta(weeks=1),
        'M': timedelta(weeks=4),
        'Q': timedelta(weeks=12),
        'Y': timedelta(weeks=52),
    }

    delay = periodDuration[kwargs['period']] * int(kwargs['multiplier'])
    ttime = time.mktime((datetime.utcnow() + delay).timetuple())

    item = blob['stack'][index]

    
    del blob['stack'][index]
    blob['snoozed'] = sorted(blob['snoozed'] + [{'item': item, 'ttime': ttime}], key=lambda x: x['ttime'])
    
    return blob


def itemToString(item):
    if type(item) == list:
        return "[%s]" % ("; ".join(map(itemToString, item)))
    return str(item)


def main():
    dbfile = '.mmintdb'
    current = sync(None, dbfile)

    while True:

        for fi in xrange(len(current['stack'])):
            i = len(current['stack']) - fi -1
            item = current['stack'][i]
            print "%s: %s" % (i, itemToString(item))
        
        print '>',
        
        try:
            line = raw_input()
        except (KeyboardInterrupt, EOFError):
            exit(0)
            
        current = matchAndRun(line, current)
        sync(current, dbfile)



if __name__ == "__main__":
    main()
        
    
