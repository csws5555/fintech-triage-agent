# Execution Plans

Use an execution plan for work that:

- changes multiple modules;
- affects persistent storage;
- changes public interfaces;
- requires a migration or rollback path;
- depends on Ollama or Chroma; or
- spans more than one roadmap step.

Keep the plan current while working. Only one implementation milestone should
be in progress at a time. Record deviations and new risks as they are
discovered.

## Reusable plan format

```markdown
# <Plan title>

## Objective

<Concrete outcome and why it is needed.>

## Roadmap source

<Document path, step numbers, and relevant headings.>

## Scope

### Included

- <In-scope behavior>

### Excluded

- <Explicit non-goals>

## Files to inspect

- `<path>` — <reason>

## Files expected to change

- `<path>` — <planned change>

## Protected files

- `<path>` — <protection rule>

## Compatibility constraints

- <Existing public APIs and callers that must remain compatible>
- <Dependency/version constraints>
- <Safety and local-only constraints>

## Implementation milestones

1. [ ] <Milestone and stop boundary>
2. [ ] <Milestone and stop boundary>

## Acceptance criteria

- [ ] <Observable behavior>
- [ ] <Required invariant>

## Testing plan

- Unit: `<exact command>`
- Integration: `<exact command or NOT_RUN reason>`
- Validation: `<exact command>`

## Live-service requirements

- Ollama: <required/not required, approved models>
- Chroma: <required/not required, expected store state>

## Rollback considerations

- <What can change persistently>
- <How the previous working state is preserved and restored>

## Progress checklist

- [ ] Repository and roadmap inspected
- [ ] Callers/imports inspected
- [ ] Implementation complete
- [ ] Documentation status updated
- [ ] Applicable tests run
- [ ] `git diff` and `git status --short` inspected

## Decisions made

- <Decision, evidence, and tradeoff>

## Unresolved risks

- <Risk, impact, and next action>

## Final results

- Files changed: <paths>
- Commands run: <exact commands>
- Results: <exact pass/fail/not-run outcomes>
- Remaining work: <next roadmap step or blocker>
```
