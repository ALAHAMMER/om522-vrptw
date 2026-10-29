# Prototype speaker notes: three presenters, about 8:45

Replace A, B, and C with your names. These are draft words: say them in your own words. Each person should run their own check (pixi run prototype-demo --checks-only) before recording.

## 1. Slide 1

PERSON A | 0:10
ON SCREEN: Title slide. Replace A, B, and C with your names before recording.

SAY, IN YOUR OWN WORDS:
We are [names], and this is our prototype for option 3: planning delivery routes. The map on the right is an actual plan our tool produced.

## 2. Slide 2

PERSON A | 0:35
ON SCREEN: The decision slide. Say this in your own words; do not read every line.

SAY, IN YOUR OWN WORDS:
Every morning, a dispatcher assigns customers to delivery trucks and chooses the stop order. Our tool reads the day's files and produces a feasible plan with low total travel time. Every customer must be served once, and service must start inside the customer's time window; arriving early means waiting. Trucks have capacity limits and shifts and must return to the depot. We compare two methods on the same data. Travel minutes are the main measure; we also report trucks used and computation time. Travel does not include waiting or service. The map shows one real day's plan: each color is one truck.

## 3. Slide 3

PERSON A | 1:05
ON SCREEN: Read each orange line out loud as you point to the code above it. The bad-file output is shown again in the live demo.

SAY, IN YOUR OWN WORDS:
My component is the input reader. It reads four CSV files: the depot, customers, vehicles, and travel times. Before solving, it checks required files and columns, value types, that every ID exists, and that service times are positive. Line 73 reads the file but keeps every value as plain text. Line 77 asks whether a column we need is missing, and line 78 stops the program and names the exact file and column. The AI's first draft let Polars guess the types, so a bad input crashed with an unhelpful message. We checked this with a copied file with window_end deleted. The tool names customers.csv and window_end, exits with a nonzero code, and writes no decision.json. The instructor's original files are never changed.

## 4. Slide 4

PERSON B | 1:10
ON SCREEN: Read each orange line out loud as you point to the code above it. If asked: T[current][c] is the travel time from where the truck is now to customer c.

SAY, IN YOUR OWN WORDS:
My component is the next-stop choice in the required rule. It takes trucks in ID order. For each truck, it looks at every customer not yet served. Lines 25 and 26 skip a customer who will not fit in the truck; a few lines below, the code skips customers the same way if the truck would miss their time window or could not get back before its shift ends. Line 33 ranks the customers that are left by travel time from where the truck is now, and a tie goes to the lower customer ID. The unclear point was what "nearest" means: travel time, not arrival time including waiting. We checked against the instructor's six-customer worked example. Our rule reproduces the visit order and 352.417 travel minutes with two trucks, and that is a required automated test. The rule is fast, but its early choices leave poor leftovers for the last trucks.

## 5. Slide 5

PERSON B | 1:00
ON SCREEN: Walk left to right through the four cards, then point to the orange band. No formulas are needed.

SAY, IN YOUR OWN WORDS:
Our second method is large neighborhood search, or LNS, adapted from published research by Ropke and Pisinger. A route is just an ordered list of customers for one truck. First, build two starting plans, the rule's plan and an insertion plan that places the hardest-to-fit customers first, and keep the better one. Then improve it with small moves that cut travel without breaking any window. Next, remove a few customers, insert them again where they fit best, and tidy up. Occasionally accept a worse draft to escape a dead end, but always keep the best feasible plan seen. Steps three and four repeat 8,000 times: that iteration count is our stopping rule, with seed 522 so every run gives the same answer, and a 480-second cap only as a safety net. It is a heuristic, so it does not guarantee the best possible answer on every new input.

## 6. Slide 6

PERSON C | 1:05
ON SCREEN: Read each orange line out loud as you point to the code above it. If asked: TOL is a tiny allowance (0.00000001 minutes) so rounding in the last decimal place is not counted as late; the instructor's checker uses the same allowance.

SAY, IN YOUR OWN WORDS:
My component is the independent checker. It reads only the input files and the exported list of visits, and recalculates every route itself. It does not import either solver. Line 62 works out the arrival time: the time we left plus the drive. Line 63 says if we arrive early, we wait until the window opens. Line 65 records a violation if service starts after the window closes. It also checks that every customer appears exactly once, capacity, and the return time. The unclear point was whether to trust the arrival times the solver writes. We do not. We tested the checker by reversing one worked-example route and dropping customer C006: it reports the late service and the missing customer, as shown at the bottom. All 37 project tests pass. Passing tests is evidence, not a promise that no bug is possible.

## 7. Slide 7

PERSON A, then C | 1:45
ON SCREEN: Switch to a large-font terminal in om522-vrptw. Run "pixi run prototype-demo", then "pixi run prototype-demo --checks-only". The slide's terminal is a summary of what you will see; the real output has more lines. Point, do not read JSON aloud. Do not quote a runtime unless the run actually shows it.

SAY, IN YOUR OWN WORDS:
A: I am running our documented demo command. It makes a new copy of the supplied medium input and runs the same solver command as pixi run solve. This new path is the fresh input. The rule gives about 1,683.4 travel minutes and 11 trucks. While the LNS runs, remember its steps: build, improve, remove and reinsert, keep the best.
C: The independent checker confirms both decisions: feasible is true and all 45 customers are served. The LNS result is about 1,040.7 minutes and eight trucks; its actual runtime and stopping status are here. This folder holds the real decision.json and summary.json, and this line previews an actual truck route. Now the checks-only command shows the missing-column rejection, the infeasible edge case, the 352.417 worked example, the checker catching our broken plan, and the automated tests passing.

## 8. Slide 8

PERSON B | 0:30
ON SCREEN: Point at the left map's long criss-crossing lines, then at the right map's compact loops.

SAY, IN YOUR OWN WORDS:
Here are both plans on the same 45 customers. Each color is one truck. The rule fills one truck at a time, so the last trucks pick up scattered leftovers: you can see the long lines crossing the map. The LNS plan uses tighter loops: 642.7 fewer travel minutes, 38 percent less, and three fewer trucks. Both plans pass the independent checker.

## 9. Slide 9

PERSON B | 0:40
ON SCREEN: You already explained the medium row on the map slide; here point to the overall pattern and the timing column.

SAY, IN YOUR OWN WORDS:
This is our initial comparison on the four supplied cases, using the same files and measures for both methods. We report travel, trucks, and runtime, and every one of these eight plans passes the independent checker. The LNS saves between 6.5 percent on the six-customer case and about 39 percent on the 120-customer case, and uses fewer trucks on the three larger cases. The cost is seconds of planning instead of an almost instant rule, at most about 28 seconds here. These timings are from saved runs on the listed laptop. These are synthetic cases, so we do not claim the savings always grow with size or apply to every network.

## 10. Slide 10

PERSON C | 0:45
ON SCREEN: Name travel times clearly. Do not add the full stress-test results or the experimental hybrid here.

SAY, IN YOUR OWN WORDS:
For the prototype, the LNS is our method: it saves substantial travel and trucks on the supplied cases, at the cost of a short planning run. For the final, our uncertain input is travel times. We will generate 30 traffic scenarios from a fixed seed and save them first, then run both medium plans unchanged on the same scenarios. We will report travel, trucks, and late service or late returns. Our limitation is that a plan that is on time with today's travel table can become late in traffic, and we will test that before making a stronger recommendation. Our README names the AI tools we used.

OPTIONAL CHANGE EXPLANATION (about 25 seconds; only if time permits):
Claude drafted the original routing tool. Codex independently reviewed it, tested alternative methods, and simplified our demonstration. One alternative saved more travel but caused more lateness in simulated traffic, so we kept the existing solver for the prototype.

BEFORE SUBMITTING (not for the video): submit the repository URL, the exact commit hash shown, and an unlisted YouTube link viewable without an access request.
