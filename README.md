
Live Deploy link:  https://fuel-route-frontend.vercel.app/

Fuel Optimizer
A Django-based API that calculates the optimal fuel stops for a truck route across the USA.

Project Overview
This project provides an API endpoint that:

Takes a Start and Finish location.
Calculates the route using OSRM (Open Source Routing Machine).
Identifies fuel stations along the route from a CSV dataset.
Optimizes fuel stops to minimize cost, respecting a 500-mile tank range.
Returns the route geometry, stops, and total fuel cost.
Algorithm Details
The fuel optimization logic is implemented in api/utils.py. The strategy is a Greedy Approach designed to minimize fuel cost while ensuring the truck never runs out of fuel.

Key Constraints:
Range: 500 miles (full tank).
MPG: 10 miles per gallon.
Start: Truck starts with a full tank.
Finish: Truck arrives at the destination with whatever fuel is left (no need to refill at the end).
Steps:
Routing:
The system fetches the route geometry (coordinates) and total distance from the OSRM API.
Station Search:
It identifies candidate fuel stations within a buffer (approx. 15 miles) of the route path.
Stations are projected onto the route to determine their exact "distance from start".
Optimization (Greedy Strategy):
The truck drives until it must refuel (i.e., when remaining range approaches 0, or specifically, before current_position + 500 miles).
Within the reachable window (current position to max range), the algorithm searches for the cheapest fuel station.
If there are multiple stations with the same lowest price, it picks the one furthest along the route (to maximize progress).
Refueling: The truck refills enough fuel to cover the distance driven since the last top-up (or start).
Cost Calculation: Gallons Needed = (Distance Driven) / 10 MPG.
Total Cost: Sum of Gallons * Price at each stop.
This process repeats until the destination is within reachable range.
Running the Project
Install dependencies:
pip install -r requirements.txt
Run migrations:
python manage.py migrate
Start the server:
python manage.py runserver
Test the API:
Visit: http://127.0.0.1:8000/api/route/?start=Dallas, TX&finish=Chicago, IL
