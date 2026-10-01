from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .utils import RouteOptimizer
import traceback

class RouteView(APIView):
    def get(self, request):
        start = request.query_params.get('start')
        finish = request.query_params.get('finish')
        
        if not start or not finish:
            return Response(
                {"error": "Please provide both 'start' and 'finish' query parameters."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            optimizer = RouteOptimizer()
            result = optimizer.optimize_route(start, finish)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            traceback.print_exc()
            return Response(
                {"error":str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
