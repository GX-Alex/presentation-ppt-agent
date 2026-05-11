# Workflow: From Brief to Pitch Deck

This workflow walks you through using PresentationAgent to turn the NovaTech AI brief into a reviewable WebDeck and exportable presentation.

---

## Prerequisites

- PresentationAgent is running locally (see [Quick Start](../README.md#quick-start))
- You have access to the chat interface at `http://localhost:3000`

## Step 1: Ingest the Source Material

**In the chat interface:**

1. Upload `examples/startup-pitch/brief.md` as an attachment
2. Or copy the entire content of `brief.md` and paste it into the chat
3. Type or paste the prompt from `examples/startup-pitch/prompt.md`

**What happens:**
- PresentationAgent processes your brief through the **briefing stage**, extracting key entities (company name, metrics, team, financial data)
- You'll see a confirmation message showing the extracted summary
- Review it and confirm to proceed

## Step 2: Evidence-First Planning

PresentationAgent converts your brief into a structured **outline** with:
- Slide titles and descriptions
- Source references for each data point (maps back to the brief)
- Suggested diagrams or charts where applicable

**Review the outline:**
- Check that all 10 requested slides are present
- Verify key data points (MRR $15,040, 91% retention, etc.) are cited
- Approve or request modifications

## Step 3: WebDeck Generation

Once the plan is approved, PresentationAgent generates slides concurrently:
- Each slide is an independent WebDeck page
- Pages are generated in parallel where dependencies allow
- A **lane-level log** shows progress for each page

**Expected duration:** 2-5 minutes depending on your model and connection

## Step 4: Review & Edit

After generation completes, explore the WebDeck:

1. **Browse slides** — Navigate through all 10 pages
2. **Edit content** — Click any text element to modify it directly
3. **Add diagrams** — Use the draw.io workspace for charts (e.g., the MRR growth chart for slide 5)
4. **Re-arrange** — Drag slides to reorder if needed

### Common edits:
- Refine the problem statement on slide 2
- Add actual numbers to growth charts
- Tweak the competitive positioning matrix

## Step 5: Export or Publish

**Export to file:**
- Use the **Export** button to generate PDF or PPTX
- Exported files appear in the `backend/data/exports/` directory

**Publish to gallery:**
- Use **Publish** to save the deck to the gallery for sharing
- Published decks can be forked and remixed

## Expected Output

Your generated presentation should include:

| Slide | Title | Key Content |
|-------|-------|-------------|
| 1 | Title | NovaTech AI · Series A Pitch Deck |
| 2 | Problem | Slow customer service, SMBs underserved |
| 3 | Solution | SmartServe AI agent |
| 4 | Product | Features overview |
| 5 | Traction | MRR growth, retention rate |
| 6 | Market | $65B TAM, 28% CAGR |
| 7 | Competition | Positioning vs Zendesk AI, Intercom Fin |
| 8 | Business Model | $199/mo + usage |
| 9 | Team | Founders + key hires |
| 10 | Ask | $5M Series A, use of funds |

> 💡 **Tip:** See `examples/startup-pitch/expected-output.md` for a detailed description of what each slide should contain.
