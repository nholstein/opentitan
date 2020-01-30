#!/usr/bin/env python3
# Copyright lowRISC contributors.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""Functions to convert validated top-level and peripheral module HJSON
to SVD files."""

import xml.etree.ElementTree as ET

import hjson
import pysvd


GENHDR = '''
  Copyright lowRISC contributors.
  Licensed under the Apache License, Version 2.0, see LICENSE for details.
  SPDX-License-Identifier: Apache-2.0

  This file generated from HJSON source by "svdgen.py", do not edit.
'''


def case_compare(left: str, right: str) -> bool:
    """Perform a case-insenstive equality check on two strings"""

    return left.casefold() == right.casefold()


def hex_or_none(num: int) -> str or None:
    """Converts None -> None and everything else to a hex string. This
    simplifies use with `svd_node()` which ignores elements whose value is
    `None`."""

    if num is None:
        return None

    return hex(num)


def extend_node(element: ET.Element, *elements: [ET.Element]) -> ET.Element:
    """Append all elements to a node and return it."""

    element.extend(elements)
    return element


def svd_node(element: str or ET.Element, **texts: {"tag": object}) -> ET.Element:
    """Construct an SVD element using the information provided.

    If the first argument is not an `ET.Element` this constructs a new
    `ET.Element` using the argument as a name. Any keyword arguments are
    created as child elements whose text contents match the stringified
    value given.

    In addition to keyword arguments, this accepts any number of additional
    positional arguments. These must be `ET.Element` objects and are
    appended to the child elements *after* any named text arguments (even
    though Python syntaxt requires specifying them *before* all named
    parameters.) This is done to improve legibility of the generated XML,
    placing the shorter, textual elements before any deeply nested tree.

    This ignores any keyword arguments whose value is `None`. This
    simplifies reading HJSON and converting it; liberal use of `hjson.get()`
    will skip any optional values which aren't set."""

    if isinstance(element, str):
        element = ET.Element(element)
    elif not isinstance(element, ET.Element):
        raise TypeError('expected str or ET.Element')

    for (tag, value) in texts.items():
        if value is None:
            continue

        text = ET.Element(tag)
        text.text = str(value)
        element.append(text)

    return element


def indent_tree(element: ET.Element, indent='\n'):
    """Pretty-print the given element. This modifies the element in place
    by tweaking the contents. It assumes that it is safe to adjust
    whitespace in the XML nodes. (This is true for SVD.)

    ElementTree prints all whitespace in the XML tree verbatim; it has
    no option to automatically indent its output. Without first touching
    this up the result is distracting to a human reader."""

    # element.text appears immediately following the element's openings
    # tag. In the case of a parent node this results in the child's
    # indentation level.
    #
    # element.tail appears immediately following the closing tag, this
    # results in padding for its next sibling/parent closing tag.
    #
    # This function takes advantage of a property of an SVD XML tree: a
    # node is either a parent or it contains text, never both.

    is_parent = len(element) != 0

    if is_parent:
        element.text = indent + '  '
    elif element.text is not None:
        element.text = element.text.strip()

    element.tail = indent

    for child in element:
        indent_tree(child, indent + '  ')
        last = child

    if is_parent:
        last.tail = indent


def generate_all_interrupts(irqs: hjson) -> [ET.Element]:
    """Generate a series of <interrupt> nodes from HJSON. Yields nothing
    if irqs is `None`. (This simplifies use in `generate_peripheral()`.)"""

    if irqs is None:
        return

    for (num, irq) in enumerate(irqs):
        yield svd_node('interrupt',
            name        = irq['name'],
            value       = num)


def sw_access_modes(reg_or_field: [hjson]) -> (pysvd.type.access, pysvd.type.readAction, pysvd.type.modifiedWriteValues):
    """Converts from OpenTitan software register access level to equivalent
    SVD access types. Whereas OpenTitan uses a single string to identify
    each different level SVD uses a combination of up to three optional
    register attributes.

    This returns a triplet of pysvd types; each individual field may be
    `None` to indicate no matching SVD field is necessary in the register
    definition. See the following pysvd enum datatypes for reference:
       * `pysvd.type.access`
       * `pysvd.type.readAction`
       * `pysvd.type.modifiedWriteValues`

    There's one interesting access level with unique semantics: "r0w1c":
    read-zero, write-one-clears. SVD doesn't have a corresponding value;
    since software can always assume the value is zero this is mapped to
    a write-only access level."""

    # SVD register read/write access types:
    read_only  = pysvd.type.access.read_only
    read_write = pysvd.type.access.read_write
    write_only = pysvd.type.access.write_only

    # SVD action when register is read:
    clear_on_read = pysvd.type.readAction.clear

    # SVD modified register write semantics:
    one_clears  = pysvd.type.modifiedWriteValues.oneToClear
    one_sets    = pysvd.type.modifiedWriteValues.oneToSet
    zero_clears = pysvd.type.modifiedWriteValues.zeroToClear

    modes = {
        None:    (None,       None,          None),
        'ro':    (read_only,  None,          None),
        'rc':    (read_only,  clear_on_read, None),
        'rw':    (read_write, None,          None),
        'r0w1c': (write_only, None,          one_clears),
        'rw1s':  (read_write, None,          one_sets),
        'rw1c':  (read_write, None,          one_clears),
        'rw0c':  (read_write, None,          zero_clears),
        'wo':    (write_only, None,          None),
    }

    return modes[reg_or_field.get('swaccess')]


def generate_bitrange(bitinfo: [int, int, int]) -> str:
    """Convert a generated `bitfield` to <bitRange> text"""

    # HJSON bitinfo contains the LSB and field width; SVD <bitRange>
    # specifies the range [LSB:MSB] inclusive.
    (width, lsb) = (bitinfo[1], bitinfo[2])
    return '[%d:%d]' % (lsb+width-1, lsb)


def generate_field(bits: hjson) -> ET.Element:
    """Convert an HJSON bit field to a <field> node"""

    (access, read_action, modified_write_values) = sw_access_modes(bits)
    return svd_node('field',
            name                = bits['name'],
            description         = bits['desc'],
            bitRange            = generate_bitrange(bits['bitinfo']),
            access              = access,
            readAction          = read_action,
            modifiedWriteValues = modified_write_values)


def generate_register(reg: hjson, base: int) -> ET.Element:
    """Convert a standard register definition into a <register> node.
    Most of the work was previously done during validation and loading
    the HJSON file; what's left is mostly transliteration."""

    # To define registers with smaller bit widths the HJSON includes a
    # single field in the register; that field has a single element
    # "bits". During `reggen.validate` the field is expanded with data
    # gleaned from the parent register.
    #
    # SVD has different semantics. Instead the register may have a
    # `<size>` element set specifying the width. (If not set, the width
    # is inherited from the parent <register> or top-level <device>.)
    #
    # When generating a register we must detect and flatten the field
    # into the register. This occurs when there is a single field whose
    # name matches the register and whose bit offset is zero. We perform
    # a case-insensitive match, as there are many registers which have
    # identical names except for being capitalized.
    fields = reg.get('fields')
    flatten = fields is not None and \
            len(fields) == 1 and \
            case_compare(fields[0]['name'], reg['name']) and \
            fields[0]['bitinfo'][2] == 0

    if flatten:
        size = fields[0]['bitinfo'][1]
    else:
        size = None

    # Ignore an empty or flattened <fields>
    def generate_all_fields(flatten: bool, fields: [hjson]) -> ET.Element:
        if not flatten and fields is not None:
            yield extend_node(svd_node('fields'), *map(generate_field, fields))

    (access, read_action, modified_write_values) = sw_access_modes(reg)
    register =  svd_node('register',
            name                = reg['name'],
            description         = reg['desc'],
            addressOffset       = hex_or_none(reg['genoffset'] - base),
            size                = size,
            mask                = hex_or_none(reg.get('genbitsused')),
            resetValue          = hex_or_none(reg.get('genresval')),
            resetMask           = hex_or_none(reg.get('genresmask')),
            access              = access,
            readAction          = read_action,
            modifiedWriteValues = modified_write_values)

    return extend_node(register, *generate_all_fields(flatten, fields))


def generate_dim_register(window: hjson, base: int) -> ET.Element:
    """Generate an SVD <register> element containing a buffer. This is
    done by setting the the <dim> subelement, indicating the register
    contains multiple items."""

    window = svd_node(generate_register(window, base),
            dim          = window['items'],
            dimIncrement = hex_or_none(int(window['genvalidbits']/8)))

    # SVD files require the magic string "%s" in the register to generate
    # a numbered offset into the window. HJSON doesn't have this; append
    # it as necessary.
    name = window.find('./name')
    if name.text.find('%s') < 0:
        name.text += '%s'

    return window


def read_genoffset(reg: hjson) -> int:
    """ Return the register's "genoffset" field. In most cases this will
    be set directly in the register's JSON fields; but "window" registers
    set this on an inner field."""

    genoffset = reg.get('genoffset')
    if genoffset is not None:
        return genoffset

    window = reg.get('window')
    if window is not None:
        return window['genoffset']

    json = hjson.dumps(reg, indent='  ', sort_keys=True, default=str)
    raise SystemExit('could not determine register "genoffset": %s' % json)


def generate_cluster(multi: [hjson], base: int) -> ET.Element:
    """Generate a <cluster> node from a multireg. The <cluster> will
    contain a <register> for each register in `genregs`.

    The <cluster> node will have its `addressOffset` set from its child
    register's lowest `genoffset`; following SVD convention all the
    <register> "addressOffset" values will be relative to the parent
    <cluster>."""

    # Correctly mapping this would require walking the nested register
    # tree and computing relative <addressOffsets>. Nested "multiregs"
    # aren't used in topgen/reggen so there's no need for the added
    # complexity.
    if base != 0:
        raise SystemExit('nesting "multireg" elements is not supported')

    genregs = multi['genregs']

    # All registers in the multiregs have their 'genoffset' set relative
    # to the peripheral. Set the cluster's addressOffset to the lowest
    # genoffset, and then generate all registers relative to this.
    #
    # We need to special case window registers: these don't specify a
    # genoffset in the outer definition; instead we need to peek inside.
    base = min(map(read_genoffset, genregs))

    cluster = svd_node('cluster',
            name          = multi['name'],
            description   = multi['desc'],
            addressOffset = hex_or_none(base))

    return extend_node(cluster, *generate_all_registers(genregs, base))


def generate_all_registers(regs: [hjson], base=0) -> [ET.Element]:
    """Convert a list of register HJSON element into a <registers> node.
    Like generating C headers, this needs to filter based on a register's
    type.

    This is a generator function; due to filtering reserved/skipped
    memory and expanding multi-registers the number of registers produced
    likely will not match the number of registers in."""

    for reg in regs:
        if 'reserved' in reg or 'skipto' in reg:
            pass
        elif 'window' in reg:
            yield generate_dim_register(reg['window'], base)
        elif 'sameaddr' in reg:
            yield from generate_all_registers(reg['sameaddr'], base)
        elif 'multireg' in reg:
            yield generate_cluster(reg['multireg'], base)
        else:
            yield generate_register(reg, base)


def generate_peripheral(module: hjson, ip: hjson) -> ET.Element:
    """Convert an IP module definition to a <peripheral> element. This
    pulls only the name and base address from the top-level HJSON."""

    registers = svd_node('registers')
    peripheral = svd_node('peripheral',
            name        = module['name'],
            baseAddress = module['base_addr'])

    return extend_node(peripheral,
            *generate_all_interrupts(ip.get('interrupt_list')),
            extend_node(registers, *generate_all_registers(ip['registers'])),
            ET.Comment('end of %s' % module['name']))


def generate_peripherals(modules: hjson, ips: {'name': hjson}) -> ET.Element:
    """Generate a <peripherals> element filled by cross-referencing the
    IP definition for each item in the top's module list."""

    return extend_node(svd_node('peripherals'),
            *(generate_peripheral(module, ips[module['type']]) for module in modules))


def generate_cpu() -> ET.Element:
    """Generate a <cpu> element. Currently all values are hardcoded as
    they are not included in either the top level or IP module HJSON.

    Multiple values are set to comply with the SVD specification, even
    though the don't apply to the ibex processor."""

    return svd_node('cpu',
            name                = pysvd.type.cpuName.other,
            endian              = pysvd.type.endian.little,
            revision            = 0,
            mpuPresent          = "false",
            fpuPresent          = "false",
            nvicPrioBits        = 0,
            vendorSystickConfig = "false")


def generate_device(top: hjson, ips: {'name': hjson}, version: str, description: str) -> ET.Element:
    """Generate an SVD <device> node from the top-level HJSON. For each
    module defined in `top` the corresponding peripheral definition is
    generated by the IP block in `ips`.

    SVD files need some basic information that isn't provided within the
    HJSON descriptions. While they might be available elsewhere in the
    configuration, it's simplest just to declare them here."""

    device = svd_node(ET.Element('device', attrib = {
                'schemaVersion': '1.1',
                'xmlns:xs': 'http://www.w3.org/2001/XMLSchema-instance',
                'xs:noNamespaceSchemaLocation': 'CMSIS-SVD.xsd',
            }),
            vendor          = 'lowRISC',
            name            = top['name'],
            version         = version,
            description     = description,
            width           = top['datawidth'],
            size            = top['datawidth'],
            addressUnitBits = 8)

    return extend_node(device,
            generate_cpu(),
            generate_peripherals(top['module'], ips))


def convert_top_to_svd(top: hjson, ips: {'name': hjson}, version: str, description: str, verify=True) -> ET.Element:
    """Convert a top-level configuration and IP register definition set
    into a System View Description ("SVD") file. This returns an
    `xml.etree.ElementTree.Element` object matching the passed HJSON.

    The input HJSON must be a top-level configuration (earlgrey) and the
    full set of IP module definitions for that configuration. These two
    will be parsed and converted into a single XML tree with a top-level
    "<device>" node. Both the top configuration and IP modules must have
    been previously validated. (see `topgen.validate_top` and `reggen.validate()`)

    If `verify` is true then the resulting SVD tree is validated using
    the `pysvd` module."""

    root = generate_device(top, ips, version, description)

    # Manually indent the XML tree. When writing out XML ElementTree
    # maintains all whitespace verbatim; skipping this step causes the
    # SVD file's newlines and indentation to match what was read from
    # the HJSON file.
    indent_tree(root)

    # Simply constructing a Device is enough to run the pysvd parser and
    # validate the structure of the XML tree.
    if verify:
        pysvd.element.Device(root)

    return root


def write_svd(device: ET.Element, output):
    """Write out the generated SVD <device> element and its children to a
    file in XML format. The SVD contents are preceeded by a comment with
    the given copyright notice and a warning that the file was generated
    by this script."""

    comment = ET.Comment(GENHDR)
    comment.tail = '\n'

    # The python3 ElementTree API doesn't natively support a top-level
    # documentation comment. Fake it for reader clarity.
    ET.ElementTree(comment).write(output, encoding='unicode', xml_declaration=True)
    ET.ElementTree(device).write(output, encoding='unicode', xml_declaration=False)