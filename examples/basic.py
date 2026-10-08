from robot_lipsync import AlignmentSpan, IncrementalArticulationCompiler

compiler = IncrementalArticulationCompiler("example-turn")
compiler.append(
    [
        AlignmentSpan("H", 0, 55, "en"),
        AlignmentSpan("i", 55, 90, "en"),
        AlignmentSpan(" ", 145, 25, "en"),
    ]
)

for event in compiler.finish():
    print(event.to_dict())
