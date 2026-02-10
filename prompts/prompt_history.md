I need you to build a modular tool-calling framework for Nella. This is the 
foundation that all future tools will plug into. It will need to support tools such as Google (Gmail, Drive, Docs, Sheets), Canva, getharvest.com, Notion, Zapier, etc.

Requirements:

1. Create src/tools/registry.py - A ToolRegistry class that:
   - Stores tool definitions (name, description, parameters JSON schema, handler function)
   - Auto-generates Claude-compatible tool schemas from registered tools
   - Supports a @tool decorator that registers async functions with their schemas
   - Groups tools by category (e.g., "google", "memory", "utility")

2. Create src/tools/base.py - A base Tool protocol/ABC with:
   - name, description, category attributes
   - parameter schema (Pydantic model that auto-converts to JSON schema)
   - async execute() method
   - A ToolResult dataclass with success/error/data fields

3. Update src/llm/client.py to support the tool-calling loop:
   - Pass registered tool schemas to Claude API calls
   - When Claude returns tool_use blocks, look up the tool in the registry,
     execute it, and return the result as tool_result
   - Support multiple sequential tool calls in one turn
   - For tools marked as requires_confirmation=True, return a pending state 
     so the Telegram handler can ask the user to confirm before executing

4. Create src/tools/utility.py with starter tools to validate the framework:
   - get_current_datetime() - returns current date, time, and timezone
   - save_note(title, content) - saves a note to a local SQLite db
   - search_notes(query) - searches saved notes

5. Write tests for the registry and tool execution loop.

Keep it clean and extensible. Every future integration (Gmail, Calendar, Drive, 
Notion, whatever) should just be a new file in src/tools/ that registers its 
tools with the registry on import. No changes to the core framework needed.

Please make sure to create (and validate) the appropriate tests for your changes.





Before I move on to Prompt 2, I'd like to focus on memory for a little bit. What I want is for Nella to have two kinds of memory. Her own memory pathway that she manages based on what she learns about me, our work together, and the world. And a memory pathway that I can interact with when I tell her to remember a thing or forget a thing. In some sense sort of a conscious memory and an unconscious one.

The unconscious memory should sort of be called regularly as we interact. The information that I share and her responses should inspected to answer a simple question: Are there facts, ideas, action items, etc in this input or outpint that I may need in the future? If so, maybe save them. This is also where she can keep tabs on all of the workstreams that we have going on. For example, perhaps we are in a long running conversation and we need to swtich gears to an entirely different topic. This would be a good time for the unconscious memory to kick in and generate and save some context so that we can pick up the thread in the future seamlessly.

For the conscious memory that I interact with I want to be able to say something like: "Hey, here's a link to an article, read it and save a quick summary in memory, I'll want to talk to you about it later." Or, "hey remmeber this phone number".

When Nella and I are interacting these two memory pathways should be working together. In other words, when something comes up in conversation and Nella remembers "oh I have something on this" that she can recall it and bring that context to the conversation. Or, when I explicitly say, "hey, remember that thing we were working on yesterday, let's pick up there" so she can pull back relelvant context.

Before you write the Claude Code prompt for this. Please decompose the problem and tell me what you understand so that I can make sure you understand my intent.





I need you to build Nella's memory system. There are two pathways that write 
to a shared memory store, and one retrieval system that reads from it.

## Shared Memory Store

Create src/memory/store.py:
- Use Mem0 as the primary memory backend (mem0ai package)
- Configure Mem0 to use Anthropic/Claude as its LLM backend
- Each memory entry should have metadata:
  - source: "automatic" or "explicit"
  - category: "fact", "preference", "action_item", "workstream", "reference", 
    "contact", "decision", or "general"
  - conversation_id: links back to when it was created
  - created_at: timestamp
  - active: boolean (soft-delete support for "forget" commands)
- Create a MemoryStore class (singleton) with methods:
  - add(content, source, category, metadata={})
  - search(query, limit=10, include_inactive=False)
  - deactivate(memory_id) - soft delete
  - list_recent(hours=24, source=None) - for debugging/review

## Pathway 1: Automatic Memory ("unconscious")

Create src/memory/automatic.py:
- After each conversation exchange (user message + Nella response), run a 
  background extraction task (don't block the Telegram response)
- The extractor sends the exchange to Claude Haiku (claude-haiku-4-5-20251001) 
  with a system prompt loaded from config/MEMORY_RULES.md
- The prompt asks Haiku to analyze the exchange and return structured JSON:
  [{"content": "...", "category": "...", "importance": "high|medium|low"}]
  or an empty array if nothing worth saving
- Only save entries with importance "medium" or "high"
- Also detect topic switches: if the conversation appears to be pivoting to a 
  new subject, generate a "workstream snapshot" that captures:
  - What we were discussing
  - What was decided
  - What's still open
  - What the next step was
  Save this as category "workstream"
- Use asyncio.create_task() so extraction runs in the background

Create config/MEMORY_RULES.md with initial content - this is the instruction 
file that governs what the automatic memory looks for. Include these starter 
rules with explanations:
- Facts about the user (preferences, contacts, relationships, important dates)
- Facts about ongoing work (project names, deadlines, decisions, blockers)
- Action items and commitments (things the user or Nella committed to doing)
- Workstream context when conversations pivot topics (capture state before switching)
- Patterns in behavior or preferences observed over time
- Key information from documents, links, or files discussed
- Names, roles, and relationships of people mentioned
- Technical decisions and their rationale
The file should be written as clear instructions to the extraction model, not 
as a schema. It should read like guidance for a smart assistant about what's 
worth jotting down.

## Pathway 2: Explicit Memory ("conscious")

Create src/tools/memory_tools.py with tools that register in the ToolRegistry:
- remember_this(content, category="general") - stores with source="explicit"
  For when the user says "remember X" or "save this"
- forget_this(query) - searches for matching memories and deactivates them
  For when the user says "forget about X"
  Should confirm what it's about to forget before deactivating
  requires_confirmation=True
- recall(query, limit=5) - explicit memory search
  For when the user says "what do you remember about X"
  Returns formatted results from both automatic and explicit memories
- save_reference(url, title, summary) - stores a link/article with summary
  For when the user says "save this article" or "remember this link"
  source="explicit", category="reference"

## Retrieval at Prompt Assembly Time

Update src/llm/prompt.py:
- Before each Claude API call, search the memory store using the user's 
  current message (and optionally the last 2-3 messages for context)
- Retrieve up to 10 relevant memories
- Inject them into the system prompt after SOUL.md and USER.md, formatted as:
  
  ## Recalled Memories
  - [automatic/fact] Bobby's mom's birthday is March 12th
  - [explicit/reference] Article: "AI in Healthcare" - summary...
  - [automatic/workstream] Last discussion about client proposal: decided on 
    approach X, still need to finalize pricing, next step is draft by Friday

- Include the source and category tags so Nella has context about where the 
  memory came from (she learned it vs was told to remember it)

## Integration

- Wire the automatic extraction into the existing message handler so it runs 
  after every exchange
- Register the memory tools with the ToolRegistry under category "memory"
- Make sure the memory store initializes on bot startup
- Add MEM0_API_KEY to .env.example (or configure Mem0 for local/self-hosted mode)
- Write tests for both pathways and retrieval

Keep Mem0 configuration flexible - I may want to switch between Mem0's hosted 
platform and self-hosted mode later. Use env vars to control this.