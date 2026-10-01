from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
from .utils import RouteOptimizer
import pandas as pd

class RouteOptimizerTests(TestCase):
    def setUp(self):
        self.optimizer = RouteOptimizer()

    @patch('api.utils.RoutingService.get_route')
    @patch('api.utils.FuelStationService')
    def test_optimize_route_simple(self, MockFuelService, mock_get_route):
        # Setup mock service instance
        mock_service_instance = MockFuelService.return_value
        
        # Mock Route: 600 miles. Start (0,0) -> Finish (10,0). roughly.
        # coords: array of [lon, lat]
        # Let's say 1 degree lon ~ 50 miles for simplicity in mock, but logic uses miles directly.
        
        mock_get_route.return_value = {
            'geometry': [[0,0], [10, 0]], # Line
            'distance': 600, # miles
            'duration': 36000,
            'start_coords': (0,0),
            'finish_coords': (0,10)
        }
        
        # Mock Stations
        # Station A at 300 miles. Price 3.00
        # Station B at 550 miles. Price 5.00
        # Station C at 100 miles. Price 2.00
        
        # We need projected distance functionality mocked or calculated.
        # In implementation, we calculate 'dist_from_start'.
        # So we should return a DataFrame with lat/lng that 'projects' correctly.
        # Or we can mock the entire `find_nearby_stations` to return a DF with pre-calculated values if implementation allowed?
        # Implementation calculates `dist_from_start` inside `optimize_route`.
        # So we must provide lat/lng that projects to 300 miles along [[0,0], [10,0]].
        # Route is straight line along X axis.
        # Total dist 600.
        # [0,0] is 0. [10,0] is 600.
        # 300 miles -> [5, 0].
        # 550 miles -> [9.16, 0].
        # 100 miles -> [1.66, 0].
        
        mock_data = {
            'Truckstop Name': ['Station A', 'Station B', 'Station C'],
            'City': ['City A', 'City B', 'City C'],
            'State': ['SA', 'SB', 'SC'],
            'Retail Price': [3.00, 5.00, 2.00],
            'lat': [0, 0, 0],
            'lng': [5.0, 9.166, 1.7] # 1.7/10 * 600 = 102 miles. 102+500 = 602 > 600.
        }
        df = pd.DataFrame(mock_data)
        mock_service_instance.find_nearby_stations.return_value = df
        
        # Logic expectations:
        # Range 500.
        # Start at 0. Range [0, 500].
        # Candidates in range: C (100, $2.00), A (300, $3.00).
        # Cheapest is C ($2.00).
        # Go to C?
        # If we go to C (100): refuel full (500). Range extends to 600.
        # Can we reach Finish (600)? Yes.
        # Cost: 
        # C is at 100. Drive 100 miles. Burn 10 gallons.
        # Refill 10 gallons at $2.00 = $20.00.
        # Arrive at Finish.
        # Total cost $20.00.
        
        # What if we skipped C?
        # Go to A (300). Range [0, 500]. A is reachable.
        # Price 3.00 > 2.00.
        # Algorithm picks Cheapest in range.
        # So it should pick C.
        
        result = self.optimizer.optimize_route("Start", "Finish")
        stops = result['stops']
        
        # Expect 1 stop at Station C probably, or maybe it optimizes differently?
        # My greedy logic: "Find candidates in range [Current+radius? No, strictly > current].
        # "Find candidates between current_pos and max_reach".
        # Sort by Price.
        # Candidates: C ($2), A ($3).
        # Best: C.
        # Move to C.
        # Refuel.
        # New Pos: 100. Range limit: 600.
        # Destination is 600.
        # Reachable? Yes.
        # Done.
        
        # Cost: 
        # C is at 102. Drive 102 miles. Burn 10.2 gallons.
        # Refill 10.2 gallons at $2.00 = $20.40.
        # Arrive at Finish.
        # Total cost $20.40.
        
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]['station'], 'Station C')
        self.assertAlmostEqual(stops[0]['cost'], 20.40)

class RouteApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('api.utils.RouteOptimizer.optimize_route')
    def test_api_endpoint(self, mock_optimize):
        mock_optimize.return_value = {'stops': [], 'total_fuel_cost': 0}
        
        response = self.client.get('/api/route/', {'start': 'A', 'finish': 'B'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        response = self.client.get('/api/route/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
