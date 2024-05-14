import os.path
import xml.etree.ElementTree as ET
import lxml.etree as etree
import json
import logging
import re
import drawio.drawio_serialization

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class XMLParseException(Exception):
    pass

class C4Lint:
    def __init__(self, xml_file, include_structurizr=False, include_ids=False):
        self.errors = {'Systems': [], 'Actors': [], 'Relationships': [], 'Other': []}
        self.c4_object_count = 0
        self.non_c4_object_count = 0
        self.xml_file = xml_file
        self.include_structurizr = include_structurizr
        self.include_ids = include_ids
        self.root = self.parse_xml(xml_file)


    def parse_xml(self, xml_file):
        try:
            tree = etree.parse(xml_file)
            xml_data = tree.findall('.//diagram')[0]
            if hasattr(xml_data, 'text'):
                try:
                    xml_string = drawio.drawio_serialization.decode_diagram(xml_data.text)
                    return ET.fromstring(xml_string)
                except Exception:
                    pass
            else:
                xml_data = xml_data.find('.//mxGraphModel')
            xml_string = ET.tostring(xml_data, encoding='utf-8').decode('utf-8')
            return ET.fromstring(xml_string)
        except Exception as e:
            error_message = f"Error parsing XML file: {xml_file}, {str(e)}"
            self.errors['Other'].append(error_message)
            raise XMLParseException(error_message)

    def check_all_systems_connected(self):
        systems = {elem.get('id'): elem for elem in self.root.findall(".//object[@c4Type='Software System']")}
        connections = {elem.get('source'): elem.get('target') for elem in self.root.findall(".//mxCell[@source][@target]")}

        for system_id in systems:
            if system_id not in connections and system_id not in connections.values():
                self.errors['Systems'].append(f"ERROR: Software System (c4Type: Software System, id: {system_id}) is not connected by any relationship.")

    def check_c4_objects(self):
        required_attribs = {'c4Name', 'c4Description', 'c4Type', 'c4Technology'}
        objects_found = False

        for elem in self.root.findall(".//object"):
            objects_found = True
            elem_attribs = set(elem.attrib.keys())
            c4_type = elem.attrib.get('c4Type', '').strip()

            if c4_type == "Relationship":
                self.c4_object_count += 1
                self.check_required_attributes(elem, {'c4Description', 'c4Technology'}, category='Relationships', is_relationship=True)
            elif 'c4Type' in elem_attribs:
                self.c4_object_count += 1
                category = 'Systems' if c4_type == 'Software System' else 'Actors'
                self.check_required_attributes(elem, {'c4Name', 'c4Description', 'c4Type'}, category=category)
            else:
                if elem_attribs.isdisjoint(required_attribs):
                    self.non_c4_object_count += 1
                    self.errors['Other'].append(f"ERROR: Non-C4 element found. Label: {elem.attrib.get('label', 'No label')}")

        if not objects_found:
            self.errors['Other'].append("ERROR: No elements of type Object found.")

    def check_required_attributes(self, elem, required_attribs, category, is_relationship=False):
        missing_attribs = [attrib for attrib in required_attribs if not elem.attrib.get(attrib, '').strip()]
        if missing_attribs:
            readable_properties = self.get_readable_properties(elem)
            missing_descr = ', '.join(missing_attribs)
            error_message = f"ERROR: '{missing_descr}' property missing ---  {readable_properties}"
            if self.include_ids:
                error_message += f" (mxCell id: {elem.attrib.get('id')})"
            self.errors[category].append(error_message)

    def get_readable_properties(self, elem):
        props = {k: v.replace('\n', ' ') for k, v in elem.attrib.items() if v.strip() and k not in {'label', 'placeholders', 'id'}}
        readable_props = ', '.join(f"{k}: {v}" for k, v in props.items())
        return readable_props or "No additional properties"

    def is_c4(self):
        required_attribs = {'c4Name', 'c4Description', 'c4Type', 'c4Technology'}
        for elem in self.root.findall(".//object"):
            elem_attribs = set(elem.attrib.keys())
            if not elem_attribs.isdisjoint(required_attribs):
                return True
        return False

    def lint(self):
        self.check_c4_objects()
        self.check_all_systems_connected()
        self.check_filename_format()
        return self.errors

    def to_structurizr(self):
        elements = []
        relationships = []
        for elem in self.root.findall(".//object"):
            c4_type = elem.attrib.get('c4Type', '').strip()
            if c4_type and c4_type != "Relationship":
                elements.append({
                    "name": elem.attrib.get('c4Name'),
                    "description": elem.attrib.get('c4Description').replace('\n', ' '),
                    "type": c4_type,
                    "technology": elem.attrib.get('c4Technology')
                })
            elif c4_type == "Relationship":
                relationships.append({
                    "source": elem.attrib.get('source'),
                    "destination": elem.attrib.get('target'),
                    "description": elem.attrib.get('c4Description').replace('\n', ' '),
                    "technology": elem.attrib.get('c4Technology')
                })
        return json.dumps({"elements": elements, "relationships": relationships}, indent=2)

    def check_filename_format(self):
        file = os.path.basename(self.xmls_file)
        filename_pattern = r"C4 L[01234] [\w\s]+\.drawio"
        if not re.match(filename_pattern, file):
            self.errors['Other'].append(f"ERROR: Filename '{self.xml_file}' does not match expected format 'C4 L<x> <system name>.drawio'")

    def __str__(self):
        def format_errors():
            error_messages = ''
            for category in ['Systems', 'Actors', 'Relationships', 'Other']:
                if self.errors[category]:
                    error_messages += f"\n\n  === {category} ===\n" + '\n'.join(
                        f"  {error}" for error in self.errors[category])
            return error_messages

        output = f"{60*'#'}\n"
        output += f"C4 Linter Input: {self.xml_file}\n"
        output += f"Include IDs in errors: {'Enabled' if self.include_ids else 'Disabled'}"

        if not any(self.errors.values()):
            if self.is_c4():
                self.lint()
                if any(self.errors.values()):
                    error_messages = format_errors()
                    structurizr_output = self.to_structurizr() if self.include_structurizr else "Disabled"
                    return f"{output}{error_messages}\n\n  === Summary === \n  {self.c4_object_count} C4 objects, {self.non_c4_object_count} non-C4 objects found.\n\n  === Structurizr Output ===\n  {structurizr_output}\n"
                else:
                    structurizr_output = self.to_structurizr() if self.include_structurizr else "Disabled"
                    return f"{output}  No linting issues detected.\n  Summary: {self.c4_object_count} C4 objects, {self.non_c4_object_count} non-C4 objects found.\n\n  === Structurizr Output ===\n  {structurizr_output}\n"
            else:
                return f"{output}  No C4 objects found. No linting performed.\n"
        else:
            error_messages = format_errors()
            return f"{output}{error_messages}\n"
