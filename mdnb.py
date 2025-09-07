#!/usr/bin/env python3

import sys, subprocess, shutil, re, textwrap
from getopt import gnu_getopt as getopt

class TextBlock():
    def __init__(self, text):
        self.text = text
    def __str__(self):
        return self.text
class CodeBlock():
    def __init__(self, code, output=None):
        self.code = code
        self._cmd = self.code.split('\n', 1)[0].lstrip('`')
        self._stdin = '\n'.join(self.code.split('\n')[1:-2])
        self.output = output
        if output != None:
            self.exit_code = int(re.findall(' exit_code="([0-9]+)"',
                                            output.split('\n', 1)[0])[0])
        else:
            self.exit_code = None
    def __str__(self):
        if self.output != None:
            return self.code + self.output
        else:
            return self.code
    def evaluate(self, timeout):
        # If we use the timeout parameter of subprocess.run for timeouts,
        # python will start leaking subprocesses. Using good old 'timeout'
        # does not have the same problem.
        res = subprocess.run(
            ['sh', '-c', f'timeout --verbose {timeout} {self._cmd}', '2>&1'],
            input=self._stdin, text=True, capture_output=True
        )
        self.output = ''.join(['::: {.output exit_code=',
                              f'"{res.returncode}"',
                               '}\n', textwrap.indent(res.stdout, '    '),
                               '\n' if res.stdout and res.stdout[-1] != '\n'
                                    else '',
                               ':::\n'])
        self.exit_code = res.returncode
    def clean(self):
        self.output = None
        self.exit_code = None
class MdNb():
    def __init__(self, filename):
        self.content = list()
        with open(filename) as f:
            source = f.readlines()
        cur = ""; context = TextBlock; i=0
        while i < len(source):
            if context == TextBlock:
                if source[i].startswith('```'):
                    self.content.append(TextBlock(cur))
                    cur = ""; cur += source[i]
                    context = CodeBlock
                else:
                    cur += source[i]
            elif context == CodeBlock:
                if source[i].startswith('```'):
                    cur += source[i]; output = None
                    if len(source) > i+1 and \
                                source[i+1].startswith('::: {.output'):
                        i += 1; output = ""
                        while i < len(source) and source[i] != ':::\n':
                            output += source[i]; i += 1
                        output += source[i]
                    self.content.append(CodeBlock(cur, output))
                    context = TextBlock; cur = ""
                else:
                    cur += source[i]
            i += 1
        # Flush the last block in the file
        if context == TextBlock:
            self.content.append(TextBlock(cur))
        else:
            raise Exception('Unterminated code blocks not yet implemented')
        # Introduce a flag to track if any changes happened that might
        # need to be written to disk
        self.dirty = False
    def __str__(self):
        return ''.join(map(str, self.content))
    def evaluate(self, timeout, strategy, verbose=False, prefix=''):
        if strategy == 'all':
            blocks = [ b for b in self.content if type(b) == CodeBlock ]
        elif strategy == 'non-zero':
            blocks = [ b for b in self.content if type(b) == CodeBlock
                       and b.output != None and b.exit_code != 0 ]
        elif strategy == 'empty':
            blocks = [ b for b in self.content if type(b) == CodeBlock
                       and b.output == None ]
        else:
            raise Exception(f"Unknown evaluation strategy '{strategy}'")
        if not blocks: return
        self.dirty = True
        n_errors = 0
        for i, b in enumerate(blocks, 1):
            if verbose:
                print(f'\r{prefix}Evaluating code blocks {i}/{len(blocks)}',
                      file=sys.stderr, end='')
            b.evaluate(timeout=timeout)
            if b.exit_code != 0: n_errors += 1
        if verbose and n_errors > 0:
            s = 's' if n_errors > 1 else ''
            print(f'  ({n_errors} error{s})', file=sys.stderr, end='')
        if verbose: print('', file=sys.stderr)
    def clean(self):
        for block in self.content:
            if type(block) == CodeBlock and block.output != None:
                self.dirty = True
                block.clean()

_cli_help = """
Usage: mdnb [OPTION]... FILE...

Options
    -t N, --timeout N       Give each code block at most N seconds to
                            terminate. Default: 120.
    -c, --clean             Remove all output from code blocks. This can be
                            useful to prepare reevaluating all code blocks.
                            Similar to how 'make clean' can be useful for
                            building something from scratch.
    -e STRATEGY,            Use STRATEGY to decide which blocks to evaluate.
      --evaluate STRATEGY   STRATEGY may be: 'all' (evaluate all code blocks
                            again), 'non-zero' (all code blocks that have a
                            non-zero exit_code) or 'empty' (only code blocks
                            that do not have any output yet). Default: empty.
    -h, --help              Print this help message and exit.

Note that mdnb modifies files in place. In order to minimize the risk of losing
valuable data, mdnb will copy FILE to FILE.orig before writing the updated FILE
to disk. If FILE.orig already exists, this existing file will be overwritten.
This is only an additional measure of guarding against data loss; and a rather
old-school one at that. Most users probably want to rely on dedicated version
control software to track changes to their notebook files as well.
""".lstrip()

def _run_cli():
    opts, files = getopt(sys.argv[1:], 't:ce:h', ['timeout=', 'clean',
                         'evaluate=', 'help'])
    # Default values
    timeout = 120; clean = False; eval_strategy = None
    for k, v in opts:
        if k in ['-t', '--timeout']:
            timeout = int(v)
        elif k in ['-c', '--clean']:
            clean = True
        elif k in ['-e', '--evaluate']:
            if v not in ['all', 'non-zero', 'empty']:
                exit(f"Unknown evaluation strategy '{v}'")
            eval_strategy = v
        elif k in ['-h', '--help']:
            print(_cli_help)
            exit(0)
    if not files:
        exit('No files were specified')
    elif clean and eval_strategy != None:
        exit('The --clean and --evaluate flags are mutually exclusive')
    if eval_strategy == None: eval_strategy = 'empty'
    for i, filename in enumerate(files, 1):
        nb = MdNb(filename)
        if clean:
            nb.clean()
        else:
            nb.evaluate(timeout=timeout, strategy=eval_strategy, verbose=True,
                prefix=f'[File {i}/{len(files)}]  ' if len(files) > 1 else '')
        if nb.dirty:
            shutil.copy(filename, f'{filename}.orig')
            with open(filename, 'w') as f:
                print(nb, file=f, end='')


if __name__ == '__main__':
    try:
        _run_cli()
    except KeyboardInterrupt:
        print('', file=sys.stderr); exit(0)
