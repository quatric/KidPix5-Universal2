"""Add a component package to an expanded product archive's Distribution.

usage: add_pkg_to_distribution.py <Distribution> <pkg id> <version> <installKBytes> <file.pkg>

The new package gets a hidden choice listed after the existing ones, so
Installer runs it after them, and the product keeps showing a single
install step.
"""
import sys
import xml.etree.ElementTree as ET


def main():
    path, pid, ver, kb, fname = sys.argv[1:6]
    tree = ET.parse(path)
    root = tree.getroot()
    if any(r.get("id") == pid for r in root.iter("pkg-ref")):
        sys.exit(f"{pid} is already in {path}")
    choice_id = pid
    default = root.find("choices-outline/line")
    ET.SubElement(default, "line", {"choice": choice_id})
    choice = ET.SubElement(root, "choice", {"id": choice_id, "visible": "false"})
    ET.SubElement(choice, "pkg-ref", {"id": pid})
    ref = ET.SubElement(root, "pkg-ref", {"id": pid, "version": ver, "onConclusion": "None",
                                         "installKBytes": kb})
    ref.text = "#" + fname
    ET.indent(tree, "    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"added {fname} ({pid} {ver})")


if __name__ == "__main__":
    main()
