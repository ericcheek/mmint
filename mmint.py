#!/usr/bin/env python

from blessed import Terminal
from datetime import timedelta, datetime
import copy
import json
import posixpath
import random
import re
import string
import time

_commandTable = []
def StackCommand(regex):
    def _command(func):
        def wrapper(db, **kwargs):
            db['stack' ] = func(db['stack'], **kwargs)
            return db

        _commandTable.append((re.compile(regex), wrapper))
        return wrapper
    
    return _command

def Command(regex):
    def _command(func):
        _commandTable.append((re.compile(regex), func))
        return func
    
    return _command


def matchAndRun(line, dbData):
    for commandRegex, commandFunc in _commandTable:
        match = commandRegex.match(line)
        if match is not None:            
            return commandFunc(copy.deepcopy(dbData), **match.groupdict())
    return dbData

def generateId():
    return 'MM' + ''.join([random.choice(string.letters + string.digits) for i in xrange(16)])

def generateTimestamp(datet=None):
    if datet is None:
        datet = datetime.utcnow()
    return int(time.mktime(datet.timetuple()))


def pathResolve(base, path):
    if not path.startswith('/'):
        path = posixpath.abspath(posixpath.join(base, path))

    return path

def pathSuffix(base, fullpath):
    return fullpath[len(posixpath.commonprefix([base, fullpath])):]

_schemaTransforms = {}
def SchemaTransform(version):
    def _trans(func):
        _schemaTransforms[version] = func

        return func
    return _trans

def checkSchema(db, dbfile):
    if type(db) is list:
        db = {
            '_schema_version': '1',
            'stack': db,
            'snoozed': []
        }

    while db['_schema_version'] in _schemaTransforms:
        # create backup before schema migration
        sync(db, '%s.bak%s' % (dbfile, generateTimestamp()))
        db = _schemaTransforms[db['_schema_version']](db)
        sync(db, dbfile)

    return db

@SchemaTransform('1')
def schema1_2(current):
    temp = {
        '_schema_version': 2,
        'stack': [],
        'snoozed': [],
        'items': {},
        'activepath': '/'
    }

    def update(item):
        if type(item) == list:
            item = [update(x) for x in item]

        id = _createItem(temp, item, '/', 'chunk' if type(item) == list else 'atom')
        return id 

    temp['stack'] = [update(x) for x in current['stack']]
    temp['snoozed'] = [{'r': update(x['item']), 't': x['ttime']} for x in current['snoozed']]

    return temp
        

def sync(current, dbfile):
    if current is None:
        try:
            with open(dbfile) as f:
                current = json.loads(f.read())
                # schema transformations
                current = checkSchema(current, dbfile)

        except IOError:
            current = checkSchema([], dbfile)
    else:
        with open(dbfile, 'w') as f:
            f.write(json.dumps(current))

    return current

def wakeup(current):
    # Perform wakeup procedures
    now = datetime.utcnow()
    
    # TODO: call custom wakeup function
    nowActive = filter(lambda x: datetime.fromtimestamp(x['t']) <= now, current['snoozed'])
    current['snoozed'] = filter(lambda x: datetime.fromtimestamp(x['t']) > now, current['snoozed'])
    current['stack'].extend(map(lambda x: x['r'], nowActive))

    # Filter path filtered items
    apath = current['activepath']
    ignored = filter(lambda ref: not current['items'][ref]['path'].startswith(apath), current['stack'])
    current['stack'] = filter(lambda ref: current['items'][ref]['path'].startswith(apath), current['stack'])
    current['snoozed'] = [{'r': ref, 't': generateTimestamp()} for ref in ignored] + current['snoozed']

    return current

def _createItem(db, payload, path, _type):    
    id = generateId()
    db['items'][id] = {
        '_type': _type,
        'path': path,
        'v': payload
    }

    # TODO: with immutable stuctures, return id and new db
    return id

def _resolve(db, ref):
    return db['items'][ref]


@Command(r"(push)? (?P<value>.*)")
def push(db, **kwargs):
    id = _createItem(db, kwargs['value'], db['activepath'], 'atom')
    db['stack'] = [id] + db['stack']
    return db

@StackCommand(r"pop")
def pop(stack, **kwargs):    
    return stack[1:]

@Command(r"chunk (?P<count>[0-9]+)")
def chunk(db, **kwargs):
    count = int(kwargs['count'])
    id = _createItem(db, db['stack'][:count], db['activepath'], 'chunk')

    db['stack'] = [id] + db['stack'][count:]

    return db

@Command(r"expand")
def expand(db, **kwargs):
    db['stack'] =  [db['stack'][0]] + _resolve(db, db['stack'][0])['v'] + db['stack'][1:]
    return db

@Command(r"explode")
def explode(db, **kwargs):
    db['stack'] =  _resolve(db, db['stack'][0])['v'] + db['stack'][1:]
    return db
    

@Command(r"mv ((?P<stackMv>(?P<src>[0-9]+) (?P<dest>[0-9]+))|(?P<pathMv>(?P<psrc>[0-9]+)? ?(?P<pdest>.*)))")
def mv(db, **kwargs):
    if kwargs['stackMv'] is not None:
        src = int(kwargs['src'])
        dest = int(kwargs['dest'])

        v = db['stack'][src]
        del db['stack'][src]
        db['stack'].insert(dest, v)


    if kwargs['pathMv'] is not None:
        src = 0 if kwargs['psrc'] is None else int(kwargs['psrc'])
        dest = pathResolve(db['activepath'], kwargs['pdest'])

        db['items'][db['stack'][src]]['path'] = dest

    
    return db

@StackCommand(r"swap ?((?P<src>[0-9]+) (?P<dest>[0-9]+))?")
def swap(stack, **kwargs):
    src = 0 if kwargs['src'] is None else int(kwargs['src'])
    dest = 1 if kwargs['dest'] is None else int(kwargs['dest'])

    v = stack[src]
    stack[src] = stack[dest]
    stack[dest] = v
    
    return stack

@StackCommand(r"cp ?(?P<src>[0-9]+)?")
def cp(stack, **kwargs):
    src = 0 if kwargs['src'] is None else int(kwargs['src'])

    return [stack[src]] + stack

@StackCommand(r"rot ?(-n (?P<count>[0-9-]+))?")
def rot(stack, **kwargs):
    count = 1 if kwargs['count'] is None else int(kwargs['count'])
    
    return [stack[(i + count) % len(stack)] for i in xrange(len(stack))]

@StackCommand(r"reverse")
def reverse(stack, **kwargs):
    stack.reverse()
    
    return stack

@Command(r"edit ?(--index (?P<index>[0-9]+))? (?P<value>.*)")
def edit(db, **kwargs):
    index = 0 if kwargs['index'] is None else int(kwargs['index'])

    ref = db['stack'][index]
    item = _resolve(db, ref)
    
    if item['_type'] != 'atom':
        print "must target atoms"
        return db
    
    db['items'][ref]['v'] = kwargs['value']    

    return db

@Command(r"apply (?P<index>[0-9]+) (?P<command>.*)")
def apply(db, **kwargs):
    index = int(kwargs['index'])
    command = kwargs['command']

    originalStack = db['stack']
    
    # TODO: assert item 0 is chunk
    db['stack'] = _resolve(db, originalStack[index])['v']
    
    db = matchAndRun(command, db)
    
    substackId = _createItem(db, db['stack'], db['activepath'], 'chunk')
    originalStack[index] = substackId
    db['stack'] = originalStack
    
    return db

@Command(r"snooze ?(--index (?P<index>[0-9]+))? (?P<multiplier>[0-9]+)(?P<period>[smhdwMqy])")
def snooze(db, **kwargs):
    index = 0 if kwargs['index'] is None else int(kwargs['index'])

    periodDuration = {
        's': timedelta(seconds=1),
        'm': timedelta(minutes=1),
        'h': timedelta(hours=1),
        'd': timedelta(days=1),
        'w': timedelta(weeks=1),
        'M': timedelta(weeks=4),
        'q': timedelta(weeks=12),
        'y': timedelta(weeks=52),
    }

    delay = periodDuration[kwargs['period']] * int(kwargs['multiplier'])
    ttime = generateTimestamp(datetime.utcnow() + delay)

    item = db['stack'][index]
    
    del db['stack'][index]
    db['snoozed'] = sorted(db['snoozed'] + [{'r': item, 't': ttime}], key=lambda x: x['t'])
    
    return db

@Command(r"cd (?P<path>.*)")
def cd(db, **kwargs):
    p = kwargs['path']

    db['activepath'] = pathResolve(db['activepath'], p)
    return db


def recursiveIter(db, ref, level=0):
    item = db['items'][ref]
    if item['_type'] == 'chunk':    
        for x in item['v']:
            for y in recursiveIter(db, x, level+1):
                yield y
    else:
        yield (item['v'], level)

def summaryPrint(db, ref, limit=None):
    spacing = "  "

    item = db['items'][ref]

    if item['_type'] == 'chunk':
        items = list(recursiveIter(db, ref))

        lineFmt = lambda (i, l): spacing*l + "- " + i

        lines = map(lineFmt, items)
        if limit!= None and len(items) > limit:
            (_, l) = items[limit]
            lines = lines[:limit] + [spacing*l + "... %s more" % (len(items) - limit)]

        return "\n" + "\n".join(lines)
    else :
        return str(item['v'])

def main():
    dbfile = '.mmintdb'
    current = sync(None, dbfile)
    current = wakeup(current)

    term = Terminal()
    with term.fullscreen():

        while True:
            print term.clear()
            
            for fi in xrange(len(current['stack'])):
                i = len(current['stack']) - fi -1
                ref = current['stack'][i]
                limit = None if i == 0 else 3
                item = _resolve(current, ref)

                suffix = "./"+pathSuffix(current['activepath'], item['path'])

                print term.red(str(i)) + " " + term.yellow(suffix) + term.red(': ') + term.white(summaryPrint(current, ref, limit=limit)) 

            print term.green('%s>' % current['activepath']),

            try:
                line = raw_input()
            except (KeyboardInterrupt, EOFError):
                break

            current = matchAndRun(line, current)
            current = sync(current, dbfile)
            current = wakeup(current)



if __name__ == "__main__":
    main()
        
    
