
from pptx import Presentation

def inspect_layout():
    prs = Presentation()
    print("Slide Layouts:")
    for i, layout in enumerate(prs.slide_layouts):
        print(f"Layout {i}: {layout.name}")
        for j, ph in enumerate(layout.placeholders):
            print(f"  Placeholder {j}: idx={ph.placeholder_format.idx}, type={ph.placeholder_format.type}, name='{ph.name}'")

inspect_layout()
