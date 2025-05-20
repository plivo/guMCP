import logging
import os
from typing import Optional

import requests

from .BaseAuthClient import BaseAuthClient, CredentialsT

logger = logging.getLogger("plivo-auth-client")


class PlivoAuthClient(BaseAuthClient[CredentialsT]):
    """
    Implementation of BaseAuthClient that uses Plivo's internal infrastructure.
    """

    def __init__(self):
        """
        Initialize the Plivo auth client
        """
        self.api_base_url = os.environ.get("PLIVO_API_BASE_URL")
        self.username = os.environ.get("PLIVO_API_USERNAME")
        self.password = os.environ.get("PLIVO_API_PASSWORD")

        if not all([self.api_base_url, self.username, self.password]):
            logger.warning(
                "Missing configuration for PlivoAuthClient. Some functionality may be limited."
            )

    def get_user_credentials(
        self, service_name: str, user_id: str
    ) -> Optional[CredentialsT]:
        """Get user credentials from Plivo API using basic auth"""

        url = f"{self.api_base_url}?service_name={service_name}&mcp_id={user_id}"

        try:
            response = requests.get(url, auth=(self.username, self.password))
            if response.status_code != 200:
                logger.error(
                    f"Failed to get credentials for {service_name} user {user_id}: {response.text}"
                )
                return None

            # Return the credentials data as a dictionary
            # The caller is responsible for converting to the appropriate credentials type
            return response.json().get("data")
        except Exception as e:
            logger.error(
                f"Error retrieving credentials for {service_name} user {user_id}: {str(e)}"
            )
            return None
