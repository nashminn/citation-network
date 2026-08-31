# Importing the GEXF files into Gephi (Windows)

These graphs are large — the full dataset is over a million nodes and three
million edges — so a plain default Gephi install on Windows will very
likely run out of memory or hang before you see anything. This doc exists
specifically to get ahead of that.

## Which file to try first

Don't start with the biggest one. Work up:

| File | Nodes | Edges | Approx. size |
|---|---|---|---|
| `citation_network_v3_depth1.gexf` | 643,732 | 1,568,372 | 861 MB |
| `citation_network_v3_depth2.gexf` | 886,531 | 2,562,527 | 1.27 GB |
| `citation_network_v3_final.gexf` | 1,020,536 | 3,036,024 | 1.49 GB |

Start with `citation_network_v3_depth1.gexf`. If that loads and Gephi stays
responsive, move up to depth2, then final. If depth1 already struggles, the
fixes below (mainly the heap size) are what to try before giving up on a
bigger file — don't jump straight to the 1.49 GB one as your first attempt.

(`citation_network.gexf`, `citation_network_influential_only.gexf`, and
`citation_network_full.gexf` are much smaller — under 8 MB each, from
earlier/smaller runs — good for a quick sanity check that Gephi itself is
working before touching the big files at all.)

## Before you even open Gephi: get the real files, not LFS pointers

These files are tracked via Git LFS. If you `git clone`/`git pull` without
LFS installed and initialized first, you'll get small text pointer files
instead of the actual data, and Gephi will fail to open them (or open an
empty/tiny "file").

```powershell
winget install GitHub.GitLFS
git lfs install
```

Do this once per machine, before pulling. If you already cloned without it,
run `git lfs pull` afterward to fetch the real content.

## The main fix: increase Gephi's memory limit

Gephi runs on the JVM, and its default max heap size (often ~1 GB) is
nowhere near enough for a million-node graph. This is the fix that matters
most — do this before trying anything else.

1. Find `gephi.conf`. It's inside your Gephi install directory, typically:
   `C:\Program Files\Gephi-x.x.x\etc\gephi.conf`
2. Open it in a text editor (as Administrator, since it's under Program
   Files — right-click your editor, "Run as administrator", then open the
   file).
3. Find the line starting with `default_options=`. It'll contain something
   like `-J-Xms64m -J-Xmx1024m`.
4. Increase the `-J-Xmx` value. As a rule of thumb, give it roughly half
   your total RAM, leaving the rest for Windows and everything else:
   - 8 GB RAM machine: try `-J-Xmx4g`
   - 16 GB RAM machine: try `-J-Xmx8g`
   - 32 GB RAM machine: try `-J-Xmx16g`
5. Save, fully close Gephi if it was open, and restart it.

If you're not sure how much RAM you have: right-click Start → Task Manager
→ Performance tab → Memory.

## Other things that help

- **Use 64-bit Gephi.** If you installed 32-bit by accident, it physically
  can't address enough memory no matter what you set `-Xmx` to. Reinstall
  the 64-bit version from gephi.org if unsure which you have.
- **Close everything else before importing.** Browser tabs, especially,
  can easily be holding a few GB. Every bit of freed RAM helps the import
  succeed instead of paging to disk.
- **Increase Windows' page file (virtual memory) as a backstop**, not a
  primary fix — it won't make things fast, but it can be the difference
  between a hard crash and a very slow-but-successful import. Settings →
  System → About → Advanced system settings → Performance Settings →
  Advanced → Virtual memory → Change → let Windows manage it, or set a
  custom size larger than your RAM if you're tight on space.
- **Be patient with the import itself.** Even with enough memory, parsing
  a 1.5 GB XML file takes real time — minutes, not seconds. If Gephi looks
  frozen but Task Manager shows it still using CPU/memory, let it keep
  going rather than force-closing it.

## After it loads: don't try to lay out a million nodes at once

Getting the file *open* in Gephi and getting a *usable visualization* are
different problems. Running a force-directed layout (ForceAtlas2, etc.) on
a million nodes will be extremely slow or effectively never finish, even on
a well-resourced machine — that's a Gephi/graph-drawing limitation, not
something the memory fix above solves.

Practical approach once the graph is loaded:
1. Go to the **Data Laboratory** or **Filters** panel.
2. Filter down to something you can actually look at — e.g. by `depth`
   (keep only depth ≤ 1 or ≤ 2 for a first look), or by `citation_count`
   (keep only well-cited papers), using the range sliders Gephi's filter
   UI gives you for numeric attributes.
3. Run layout algorithms on that filtered, much smaller subgraph.
4. Once you know what you want to look at, you can widen the filter
   gradually.

## If it's still too much: generate a smaller file instead of fighting Gephi

If even `citation_network_v3_depth1.gexf` won't cooperate, it's often
easier to make a genuinely smaller GEXF file up front than to keep fighting
memory settings. The project's own `export_gexf.py` reads directly from the
SQLite DB (`citation_network_v3.db`) and can be pointed at a query that
only pulls a subset — e.g. everything at depth ≤ 1, or everything above a
citation-count threshold — rather than the whole graph. That's a Python/DB
change rather than a Gephi setting, so ask if you want a specific filtered
export built for you instead of wrestling with the full file on a
memory-constrained machine.
