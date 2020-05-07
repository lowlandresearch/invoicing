#!/usr/bin/env python3
import sys
from pathlib import Path
from datetime import date
import tempfile
import pprint
import shutil

import click
import toolz.curried as _
import larc.common as __
import larc
import pyperclip
import dateutil.parser
import jinja2
from ruamel.yaml.comments import CommentedMap

log = larc.logging.new_log(__name__)

HERE = Path(__file__).expanduser().resolve().parent

latex_paths = {
    'fonts': Path(HERE, 'Fonts'),
    'dapper': Path(HERE, 'dapper-invoice.cls'),
    'make': Path(HERE, 'Makefile'),
    'icon': Path(HERE, 'larc-icon.png'),
}

def format_date(dt):
    return dt.strftime('%Y/%m/%d')
parse_format = _.compose_left(
    dateutil.parser.parse,
    format_date,
)

@_.curry
def hour_transform(rates, hour):
    return _.merge(
        hour,
        {'date': parse_format(hour['date']),
         'rate': rates[hour.get('rate', 'default')]},
    )

def transform_env(env):
    return env

def invoice_template():
    return _.pipe(
        jinja2.Environment(
            variable_start_string='||',
            variable_end_string='||',
            block_start_string='<|',
            block_end_string='|>',
            comment_start_string='<#',
            comment_end_string='#>',
            loader=jinja2.FileSystemLoader(str(HERE)),
        ),
        transform_env,
        lambda e: e.get_template(
            'invoice.tex.j2'
        ),
    )

def invoice_tex_path(path):
    return Path(path.parent, f'{path.stem}.tex')
        
def invoice_pdf_path(path):
    return Path(path.parent, f'{path.stem}.pdf')

def copy_to_temp(temp_path, invoice):
    temp_invoice = Path(temp_path, invoice.name)
    shutil.copy(invoice, temp_path)
    fonts = latex_paths['fonts']
    shutil.copytree(fonts, Path(temp_path, fonts.name))
    for key in set(latex_paths) - {'fonts'}:
        shutil.copy(latex_paths[key], temp_path)
    return temp_invoice
        
@click.group()
@click.option('--loglevel', default='info')
def main(loglevel):
    larc.logging.setup_logging(loglevel)

@main.command()
@click.argument(
    'invoice', type=click.Path(exists=True),
    # help='YAML invoice to convert to PDF'
)
@click.option(
    '-o', '--output-dir', default='.'
)
def render(invoice, output_dir):
    invoice = Path(invoice)
    data = larc.yaml.read_yaml(invoice)
    data = _.merge(
        data,
        {'due': data['due']},
        {'hours': _.pipe(
            data['hours'],
            _.map(hour_transform(data['rates'])),
            tuple
        )},
    )
    pprint.pprint(data)
    data = _.merge(
        data,
        {'balance': _.pipe(
            data['hours'],
            _.map(lambda h: h['hours'] * h['rate']),
            sum,
        )},
        {'due_in': (data['due'] - date.today()).days},
    )

    with tempfile.TemporaryDirectory() as tempdir:
        temp_path = Path(tempdir)
        temp_invoice = copy_to_temp(temp_path, invoice)

        template = invoice_template()
        tex_path, pdf_path = (
            invoice_tex_path(temp_invoice),
            invoice_pdf_path(temp_invoice)
        )
        log.info(f'Rendering invoice to {pdf_path}')
        tex_path.write_text(template.render(invoice=data))
        log.info(larc.shell.getoutput(
            f'make {pdf_path.name}',
            cwd=temp_path,
        ))
        shutil.copy(
            pdf_path, Path(output_dir, pdf_path.name)
        )

@main.command()
@click.option(
    '-c', '--to-clipboard', is_flag=True,
)
@click.option(
    '-C', '--from-clipboard', is_flag=True,
)
def format_hours(to_clipboard, from_clipboard):
    hours = []
    if from_clipboard:
        hours = _.pipe(
            pyperclip.paste().splitlines(),
            _.map(lambda l: l.split('\t')),
            tuple,
        )
        log.info(hours)
        if len(hours[0]) == 2:
            hours = [tuple(_.concatv(h, [''])) for h in hours]

    output_func = sys.stdout.write
    if to_clipboard:
        output_func = pyperclip.copy

    _.pipe(
        hours,
        _.map(lambda h: CommentedMap(
            [('date', parse_format(h[0])),
             ('hours', float(h[1])),
             ('desc', h[2])]
        )),
        tuple,
        larc.yaml.dump,
        output_func,
    )

if __name__ == '__main__':
    main()

