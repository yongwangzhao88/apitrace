#!/usr/bin/env python
##########################################################################
#
# Copyright 2011 Jose Fonseca
# All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the 'Software'), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
##########################################################################/

'''Run two retrace instances in parallel, comparing generated snapshots.
'''


import optparse
import os.path
import re
import shutil
import subprocess
import platform
import sys
import tempfile

from PIL import Image

from snapdiff import Comparer
import jsondiff


# Null file, to use when we're not interested in subprocesses output
if platform.system() == 'Windows':
    NULL = open('NUL:', 'wt')
else:
    NULL = open('/dev/null', 'wt')


class Setup:

    def __init__(self, args, env=None):
        self.args = args
        self.env = env

    def retrace(self):
        cmd = [
            options.retrace,
            '-s', '-',
            '-S', options.snapshot_frequency,
        ] + self.args
        p = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=NULL)
        return p

    def dump_state(self, call_no):
        '''Get the state dump at the specified call no.'''

        cmd = [
            options.retrace,
            '-D', str(call_no),
        ] + self.args
        p = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=NULL)
        state = jsondiff.load(p.stdout)
        p.wait()
        return state


def read_pnm(stream):
    '''Read a PNM from the stream, and return the image object, and the comment.'''

    magic = stream.readline()
    if not magic:
        return None, None
    assert magic.rstrip() == 'P6'
    comment = ''
    line = stream.readline()
    while line.startswith('#'):
        comment += line[1:]
        line = stream.readline()
    width, height = map(int, line.strip().split())
    maximum = int(stream.readline().strip())
    assert maximum == 255
    data = stream.read(height * width * 3)
    image = Image.frombuffer('RGB', (width, height), data, 'raw', 'RGB', 0, 1)
    return image, comment


def diff_state(setup, ref_call_no, src_call_no):
    '''Compare the state between two calls.'''

    ref_state = setup.dump_state(ref_call_no)
    src_state = setup.dump_state(src_call_no)
    sys.stdout.flush()
    differ = jsondiff.Differ(sys.stdout)
    differ.visit(ref_state, src_state)
    sys.stdout.write('\n')


def parse_env(optparser, entries):
    '''Translate a list of NAME=VALUE entries into an environment dictionary.'''

    env = os.environ.copy()
    for entry in entries:
        try:
            name, var = entry.split('=', 1)
        except Exception:
            optparser.error('invalid environment entry %r' % entry)
        env[name] = var
    return env


def main():
    '''Main program.
    '''

    global options

    # Parse command line options
    optparser = optparse.OptionParser(
        usage='\n\t%prog [options] -- [glretrace options] <trace>',
        version='%%prog')
    optparser.add_option(
        '-r', '--retrace', metavar='PROGRAM',
        type='string', dest='retrace', default='glretrace',
        help='retrace command [default: %default]')
    optparser.add_option(
        '--ref-env', metavar='NAME=VALUE',
        type='string', action='append', dest='ref_env', default=[],
        help='add variable to reference environment')
    optparser.add_option(
        '--src-env', metavar='NAME=VALUE',
        type='string', action='append', dest='src_env', default=[],
        help='add variable to source environment')
    optparser.add_option(
        '--diff-prefix', metavar='PATH',
        type='string', dest='diff_prefix', default='.',
        help='prefix for the difference images')
    optparser.add_option(
        '-t', '--threshold', metavar='BITS',
        type="float", dest="threshold", default=12.0,
        help="threshold precision  [default: %default]")
    optparser.add_option(
        '-S', '--snapshot-frequency', metavar='FREQUENCY',
        type="string", dest="snapshot_frequency", default='draw',
        help="snapshot frequency: frame, framebuffer, or draw  [default: %default]")

    (options, args) = optparser.parse_args(sys.argv[1:])
    ref_env = parse_env(optparser, options.ref_env)
    src_env = parse_env(optparser, options.src_env)
    if not args:
        optparser.error("incorrect number of arguments")

    ref_setup = Setup(args, ref_env)
    src_setup = Setup(args, src_env)

    image_re = re.compile('^Wrote (.*\.png)$')

    last_good = -1
    last_bad = -1
    ref_proc = ref_setup.retrace()
    try:
        src_proc = src_setup.retrace()
        try:
            while True:
                # Get the reference image
                ref_image, ref_comment = read_pnm(ref_proc.stdout)
                if ref_image is None:
                    break

                # Get the source image
                src_image, src_comment = read_pnm(src_proc.stdout)
                if src_image is None:
                    break

                assert ref_comment == src_comment

                call_no = int(ref_comment.strip())

                # Compare the two images
                comparer = Comparer(ref_image, src_image)
                precision = comparer.precision()

                sys.stdout.write('%u %f\n' % (call_no, precision))

                if precision < options.threshold:
                    if options.diff_prefix:
                        prefix = os.path.join(options.diff_prefix, '%010u' % call_no)
                        prefix_dir = os.path.dirname(prefix)
                        if not os.path.isdir(prefix_dir):
                            os.makedirs(prefix_dir)
                        ref_image.save(prefix + '.ref.png')
                        src_image.save(prefix + '.src.png')
                        comparer.write_diff(prefix + '.diff.png')
                    if last_bad < last_good:
                        diff_state(src_setup, last_good, call_no)
                    last_bad = call_no
                else:
                    last_good = call_no

                sys.stdout.flush()
        finally:
            src_proc.terminate()
    finally:
        ref_proc.terminate()


if __name__ == '__main__':
    main()
