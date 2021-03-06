#!/usr/bin/env python3
# Copyright lowRISC contributors.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
r"""Command line wrapper tool to generate RAL pkg using regtool as well as a corresponding
fusesoc core file
"""
import argparse
import os
import sys
from textwrap import dedent as dedent


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ip_name", metavar='<ip-name>', help='Name of the IP')
    parser.add_argument(
        "-t",
        "--top",
        default=False,
        action='store_true',
        help='Indicate whether the RAL model generation is for the top level')
    parser.add_argument(
        "csr_hjson",
        metavar='<hjson-file>',
        help='Input Hjson file capturing the CSR specification for the IP')
    parser.add_argument(
        '-o',
        '--outdir',
        default='.',
        help=
        'Target output directory for placing the RAL pkg as well as the fusesoc core file'
    )
    args = parser.parse_args()

    # check if csr_hjson is a valid file
    if not os.path.exists(args.csr_hjson):
        print("RAL Hjson spec file " + args.csr_hjson + " does not exist!" + \
              "\nExitting without error.")
        sys.exit(0)

    # check if outdir exists
    if not os.path.exists(args.outdir):
        print("ERROR: Outdir " + args.outdir + " does not exist! Create it first." + \
              "\nExitting with error.")
        sys.exit(1)

    # generate the ral pkg
    self_path = os.path.dirname(os.path.realpath(__file__))
    ral_tool_path = os.path.abspath(os.path.join(self_path, "../../../util"))

    if args.top:
        os.system(ral_tool_path + "/topgen.py -r -o " + args.outdir + ' -t ' +
                  args.csr_hjson)
    else:
        os.system(ral_tool_path + "/regtool.py -s -t " + args.outdir + ' ' +
                  args.csr_hjson)

    # create fusesoc core file
    text = """
           CAPI=2:
           # Copyright lowRISC contributors.
           # Licensed under the Apache License, Version 2.0, see LICENSE for details.
           # SPDX-License-Identifier: Apache-2.0

           name: "lowrisc:dv:gen_ral_pkg"
           description: \"%s UVM RAL pkg
                         Auto-generated by hw/dv/tools/gen_ral_pkg.py\"
           filesets:
             files_dv:
               depend:
                 - lowrisc:dv:dv_lib
               files:
                 - %s_ral_pkg.sv
               file_type: systemVerilogSource

           targets:
             default:
               filesets:
                 - files_dv
           """ % (args.ip_name.upper(), args.ip_name)
    text = dedent(text).strip()

    with open(args.outdir + "/" + "gen_ral_pkg.core", 'w') as fout:
        try:
            fout.write(text)
        except IOError:
            log.error(exceptions.text_error_template().render())


if __name__ == '__main__':
    main()
