# Zyven

Zyven compiles a library into a verified skill: tools an agent can call, kept only when they pass every gate.

## Verification

**Tester**:
The compile role that writes differential cases from the spec and the library alone, never seeing the adapter code.
_Avoid_: test writer, test generator

**Differential case**:
One check that a tool, given some arguments, returns in one field exactly what the library itself computes.
_Avoid_: diff test, reference test

**Reference program**:
The Tester's code for a differential case: optional setup lines, then a last line that evaluates to the library's value.
_Avoid_: reference expression (that names only the last line)

**Valid reference program**:
A reference program that evaluates without raising on its own case's arguments; whether it matches the tool does not matter.
_Avoid_: working reference, passing reference
