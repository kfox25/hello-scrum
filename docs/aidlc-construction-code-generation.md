# Code Generation - Detailed Steps
*Source: [awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows) — `aidlc-rules/aws-aidlc-rule-details/construction/code-generation.md`*

---

## Overview
Two integrated parts:
- **Part 1 - Planning**: Create detailed code generation plan with explicit steps
- **Part 2 - Generation**: Execute approved plan to generate code, tests, and artifacts

**Note**: For brownfield projects, "generate" means modify existing files when appropriate, not create duplicates.

## Prerequisites
- Unit Design Generation must be complete for the unit
- NFR Implementation (if executed) must be complete for the unit
- All unit design artifacts must be available

---

# PART 1: PLANNING

## Step 1: Analyze Unit Context
- [ ] Read unit design artifacts from Unit Design Generation
- [ ] Read unit story map to understand assigned stories
- [ ] Identify unit dependencies and interfaces
- [ ] Validate unit is ready for code generation

## Step 2: Create Detailed Unit Code Generation Plan
- [ ] Read workspace root and project type from `aidlc-docs/aidlc-state.md`
- [ ] Determine code location (see Critical Rules for structure patterns)
- [ ] **Brownfield only**: Review `reverse-engineering/code-structure.md` for existing files to modify
- [ ] Document exact paths (never aidlc-docs/)
- [ ] Create explicit steps for unit generation:
  - Project Structure Setup (greenfield only)
  - Business Logic Generation
  - Business Logic Unit Testing
  - Business Logic Summary
  - API Layer Generation
  - API Layer Unit Testing
  - API Layer Summary
  - Repository Layer Generation
  - Repository Layer Unit Testing
  - Repository Layer Summary
  - Frontend Components Generation (if applicable)
  - Frontend Components Unit Testing (if applicable)
  - Frontend Components Summary (if applicable)
  - Database Migration Scripts (if data models exist)
  - Documentation Generation (API docs, README updates)
  - Deployment Artifacts Generation
- [ ] Number each step sequentially
- [ ] Include story mapping references
- [ ] Add checkboxes [ ] for each step

## Step 3: Include Unit Generation Context
- Stories implemented by this unit
- Dependencies on other units/services
- Expected interfaces and contracts
- Database entities owned by this unit
- Service boundaries and responsibilities

## Step 4: Create Unit Plan Document
- [ ] Save as `aidlc-docs/construction/plans/{unit-name}-code-generation-plan.md`
- [ ] Include step numbering, unit context, dependencies, story traceability

## Steps 5–9: Summarize, Log, Approval
- Summarize plan to user
- Log approval prompt in `aidlc-docs/audit.md`
- Wait for explicit user approval
- Record approval response
- Mark Code Generation Part 1 complete in `aidlc-state.md`

---

# PART 2: GENERATION

## Step 10: Load Unit Code Generation Plan
- [ ] Read plan from `aidlc-docs/construction/plans/{unit-name}-code-generation-plan.md`
- [ ] Identify next uncompleted step (first [ ] checkbox)

## Step 11: Execute Current Step
- [ ] Verify target directory (never aidlc-docs/)
- [ ] **Brownfield only**: Check if target file exists
  - **If file exists**: Modify in-place (NEVER create `ClassName_modified.java`, `ClassName_new.java`, etc.)
  - **If file doesn't exist**: Create new file
- [ ] Write to correct locations:
  - **Application Code**: Workspace root per project structure
  - **Documentation**: `aidlc-docs/construction/{unit-name}/code/` (markdown only)
  - **Build/Config Files**: Workspace root

## Step 12: Update Progress
- [ ] Mark completed step as [x]
- [ ] Mark associated unit stories as [x] when their generation is finished
- [ ] Update `aidlc-docs/aidlc-state.md`
- [ ] **Brownfield only**: Verify no duplicate files created

## Step 13: Continue or Complete
- [ ] If more steps remain, return to Step 10
- [ ] If all steps complete, proceed to completion message

## Step 14: Present Completion Message

```markdown
# 💻 Code Generation Complete - [unit-name]

> **📋 REVIEW REQUIRED:**
> - **Application Code**: `[actual-workspace-path]`
> - **Documentation**: `aidlc-docs/construction/[unit-name]/code/`

> **🚀 WHAT'S NEXT?**
> 🔧 **Request Changes** - Ask for modifications based on your review
> ✅ **Continue to Next Stage** - Proceed to **[next-unit/Build & Test]**
```

## Steps 15–16: Approval and Progress
- Wait for explicit approval
- Log approval in audit.md with timestamp
- Mark Code Generation complete for this unit in aidlc-state.md

---

## Critical Rules

### Code Location Rules
- **Application code**: Workspace root only (NEVER aidlc-docs/)
- **Documentation**: aidlc-docs/ only (markdown summaries)

**Structure patterns by project type**:
- **Brownfield**: Use existing structure
- **Greenfield single unit**: `src/`, `tests/`, `config/` in workspace root
- **Greenfield multi-unit (microservices)**: `{unit-name}/src/`, `{unit-name}/tests/`
- **Greenfield multi-unit (monolith)**: `src/{unit-name}/`, `tests/{unit-name}/`

### Brownfield File Modification Rules
- Check if file exists before generating
- If exists: Modify in-place (never create copies)
- If doesn't exist: Create new file
- Verify no duplicate files after generation

### Automation Friendly Code Rules
When generating UI code, add `data-testid` attributes to interactive elements:
- Naming: `{component}-{element-role}` (e.g., `login-form-submit-button`)
- Avoid dynamic or auto-generated IDs
- Keep `data-testid` values stable across code changes

## Completion Criteria
- Complete unit code generation plan created and approved
- All steps marked [x]
- All unit stories implemented
- All code and tests generated
- Deployment artifacts generated
- Unit ready for Build & Test phase

---

## Hello Scrum Mapping

In hello-scrum, Code Generation is performed by `agent.py`:
- **Part 1 (Planning):** Agent reads story + AC and determines patches to apply
- **Part 2 (Generation):** Agent generates JSON patches applied to `index.html`
- Hermes (claude-haiku) acts as the approval gate (code_review stage)
- AC check verifies acceptance criteria are met before marking done
