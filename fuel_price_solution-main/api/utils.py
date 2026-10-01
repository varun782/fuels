import pandas as pd
from django.conf import settings
from shapely.geometry import Point, LineString
from uszipcode import SearchEngine
import os
import requests
import json
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import math

class FuelStationService:
    _instance = None
    df = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FuelStationService, cls).__new__(cls)
            cls._instance.load_data()
        return cls._instance

    def load_data(self):
        csv_path = getattr(settings, 'FUEL_PRICES_CSV', None)
        if not csv_path or not os.path.exists(csv_path):
            raise FileNotFoundError(f"Fuel prices CSV not found at {csv_path}")
        
        # Load CSV
        self.df = pd.read_csv(csv_path)
        
        # Data cleaning: ensure column names are compatible
        self.df.columns = [c.strip() for c in self.df.columns]
        
        # Rename for consistency if needed, but let's stick to Retail Price
        if 'Retail Price' not in self.df.columns:
            # Maybe it is different?
            pass

        processed_path = csv_path + '.processed.json'
        if os.path.exists(processed_path):
            print("Loading cached station data...")
            self.df = pd.read_json(processed_path)
        else:
            print("Geocoding stations... this may take a moment.")
            search = SearchEngine()
            
            def get_coords(row):
                city = row.get('City', '').strip()
                state = row.get('State', '').strip()
                # Simple cleaning
                if not city or not state:
                    return pd.Series({'lat': None, 'lng': None})
                
                try:
                    res = search.by_city_and_state(city, state)
                    if res:
                        return pd.Series({'lat': res[0].lat, 'lng': res[0].lng})
                except Exception:
                    # If geocoding fails for any reason, return None and skip this station
                    pass
                return pd.Series({'lat': None, 'lng': None})

            # unique city/state combos
            unique_locs = self.df[['City', 'State']].drop_duplicates()
            print(f"Unique locations to geocode: {len(unique_locs)}")
            
            coords_list = []
            for i, row in unique_locs.iterrows():
                if i % 100 == 0:
                    print(f"Geocoding {i}/{len(unique_locs)}...", end='\r')
                coords_list.append(get_coords(row))
            print("Geocoding complete.")
            
            coords = pd.DataFrame(coords_list)
            # Ensure index alignment
            coords.index = unique_locs.index
            
            unique_locs = pd.concat([unique_locs, coords], axis=1)
            
            # Merge back
            self.df = self.df.merge(unique_locs, on=['City', 'State'], how='left')
            self.df = self.df.dropna(subset=['lat', 'lng'])
            self.df.to_json(processed_path)
            print(f"Cached {len(self.df)} stations.")

    def find_nearby_stations(self, route_coords, buffer_deg=0.2):
        """
        route_coords: List of [lon, lat] from OSRM
        buffer_deg: approx 10-15 miles
        """
        if self.df is None or self.df.empty:
            return pd.DataFrame()

        # Create LineString from route
        # route_coords is [lon, lat]
        route_line = LineString(route_coords)
        
        # Quick bounding box filter first
        min_x, min_y, max_x, max_y = route_line.bounds
        buffer = buffer_deg
        
        candidates = self.df[
            (self.df['lng'] >= min_x - buffer) &
            (self.df['lng'] <= max_x + buffer) &
            (self.df['lat'] >= min_y - buffer) &
            (self.df['lat'] <= max_y + buffer)
        ].copy()
        
        if candidates.empty:
            return candidates

        # Precise filter using Shapely distance
        # We can optimize by converting candidates to geometry
        # But iterating 1000 candidates is fast enough
        def is_close(row):
            pt = Point(row['lng'], row['lat'])
            return route_line.distance(pt) <= buffer

        candidates['is_close'] = candidates.apply(is_close, axis=1)
        return candidates[candidates['is_close']]


class RoutingService:
    def get_route(self, start_str, finish_str):
        # 1. Geocode start/finish
        geolocator = Nominatim(user_agent="fuel_optimizer_app")
        try:
            start_loc = geolocator.geocode(start_str)
            finish_loc = geolocator.geocode(finish_str)
        except GeocoderTimedOut:
            raise Exception("Geocoding service timed out.")

        if not start_loc or not finish_loc:
            raise Exception("Could not geocode locations.")

        # 2. Call OSRM
        # coordinates: lon,lat
        url = f"http://router.project-osrm.org/route/v1/driving/{start_loc.longitude},{start_loc.latitude};{finish_loc.longitude},{finish_loc.latitude}?overview=full&geometries=geojson"
        
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception("Routing service failed.")
        
        data = response.json()
        if data['code'] != 'Ok':
            raise Exception(f"Routing error: {data.get('message')}")
        
        route = data['routes'][0]
        return {
            'geometry': route['geometry']['coordinates'], # List of [lon, lat]
            'distance': route['distance'] * 0.000621371, # Convert meters to miles
            'duration': route['duration'], # seconds
            'start_coords': (start_loc.latitude, start_loc.longitude),
            'finish_coords': (finish_loc.latitude, finish_loc.longitude)
        }

class RouteOptimizer:
    def optimize_route(self, start, finish):
        # 1. Get Route
        router = RoutingService()
        route_data = router.get_route(start, finish)
        route_coords = route_data['geometry'] # [lon, lat]
        total_dist_miles = route_data['distance']
        
        # 2. Get Stations along route
        fuel_service = FuelStationService()
        stations = fuel_service.find_nearby_stations(route_coords)
        
        # 3. Optimize Stops
        # Simple Greedy Algorithm:
        # Range = 500 miles.
        # MPG = 10.
        # Start with full tank.
        
        stops = []
        current_dist = 0
        fuel_range = 500
        total_fuel_cost = 0
        
        # We need to calculate distance of each station ALONG the route.
        # This is non-trivial with just coords.
        # Approximation: Project station onto route LineString and get distance from start.
        
        route_line = LineString(route_coords)
        
        if stations.empty:
            if total_dist_miles > 500:
                raise Exception("No stations found along route, cannot complete trip!")
            return {
                'route': route_data,
                'stops': [],
                'total_fuel_cost': 0 # No stops needed
            }
            
        # Calculate distance from start for each station
        def get_dist_from_start(row):
            pt = Point(row['lng'], row['lat'])
            return route_line.project(pt, normalized=True) * total_dist_miles

        stations['dist_from_start'] = stations.apply(get_dist_from_start, axis=1)
        stations = stations.sort_values('dist_from_start')
        
        # Logic
        current_pos = 0 # miles
        
        while current_pos + 500 < total_dist_miles:
            # We need to refuel before current_pos + 500
            max_reach = current_pos + 500
            
            # Candidates: stations between current_pos and max_reach
            candidates = stations[
                (stations['dist_from_start'] > current_pos) & 
                (stations['dist_from_start'] <= max_reach)
            ]
            
            if candidates.empty:
                raise Exception(f"Stranded at mile {current_pos}. No stations within range.")
            
            # Optimal strategy:
            # Find closest station to max_reach? No, cheapest in range.
            # If multiple cheapest, furthest one (closest to max_reach).
            
            best_candidate = candidates.sort_values(['Retail Price', 'dist_from_start'], ascending=[True, False]).iloc[0]
            
            # Calculate cost
            # How much fuel to buy?
            # Greedy: Fill up.
            # Gallons needed = (Distance driven since last fill) / MPG
            dist_driven = best_candidate['dist_from_start'] - current_pos
            gallons = dist_driven / 10.0
            cost = gallons * best_candidate['Retail Price']
            
            stops.append({
                'station': best_candidate['Truckstop Name'],
                'city': best_candidate['City'],
                'state': best_candidate['State'],
                'price': best_candidate['Retail Price'],
                'lat': best_candidate['lat'],
                'lng': best_candidate['lng'],
                'gallons': gallons,
                'cost': cost,
                'dist_from_start': best_candidate['dist_from_start']
            })
            
            total_fuel_cost += cost
            current_pos = best_candidate['dist_from_start']
            
        # Final leg
        # Start --> Stop 1 --> Stop 2 --> Finish
        # We pay for fuel used to reach Stop 1, Stop 2... 
        # But we arrive at Finish. Do we pay for the fuel used on the last leg?
        # "Return the total money spent on fuel".
        # If I arrive at destination with 100 miles of fuel left, I paid for it.
        # So yes, usually simple accounting: Cost at Pump 1 + Cost at Pump 2.
        # The fuel used for the LAST leg is not "replaced" at the destination.
        # So the cost calculation above covers the fuel used to GET TO the stops.
        # But checking the requirements:
        # "Return map of route... optimal location to fuel up... total money spent".
        
        # Wait, if I start full, and drive 400 miles to Stop 1. I buy 40 gallons.
        # Then I drive 200 miles to finish. I buy 0 gallons.
        # Total spent = Cost of 40 gallons. 
        # This covers the first 400 miles. The last 200 miles are "free" (using the remaining tank).
        # THIS IS THE STANDARD INTERPRETATION OF "MONEY SPENT".
        # Unless "Return fuel cost for the TRIP".
        # If trip cost, then (Total Distance / 10) * Average Price? No.
        # I will stick to "Money spent at pumps". 
        # This incentivizes stretching the last leg as much as possible without refueling.
        
        return {
            'route': route_data,
            'stops': stops,
            'total_fuel_cost': round(total_fuel_cost, 2),
            'map_url': f"http://geojson.io/#data=data:application/json,{json.dumps({'type': 'LineString', 'coordinates': route_coords})}" 
            # Note: Just returning geometry for frontend to render is better.
        }

