# Affiliate Service API Documentation

## Creator API Endpoints

### Get Creator Stats
Retrieves statistics and data for a creator's affiliate performance within a specified date range. This endpoint provides summarized betting data for all users under your affiliate code, including total wagers, number of bets, and user information.

**Endpoint:** `/affiliate/creator/get-stats`  
**Method:** `POST`  
**Cooldown:** 5 minutes (300 seconds)  
**Rate Limit:** One request per 5 minutes per API key

#### Request Parameters

| Parameter | Type   | Required | Description                                           | Default                | Constraints |
|-----------|--------|----------|-------------------------------------------------------|------------------------|-------------|
| apikey    | string | Yes      | Creator's API key (max 100 characters)                | -                      | Max length: 100 chars |
| from      | date   | No       | Start date for the date range (YYYY-MM-DD)           | 7 days ago            | Cannot be future date |
| to        | date   | No       | End date for the date range (YYYY-MM-DD)             | Current date          | Cannot be future date |

#### Example Request
```json
{
    "apikey": "your_api_key_here",
    "from": "2025-01-24",
    "to": "2025-01-31"
}
```

#### Response Structure
```json
{
    "error": false,
    "data": {
        "affiliate": {
            "id": number,            // Unique identifier for the affiliate
            "code": string,          // Your affiliate code
            "createdAt": date,       // When the affiliate account was created
            "claimableBalance": number, // Current claimable balance in cents
            "totalEarned": number,   // Total lifetime earnings in cents
            "totalWagered": number   // Total lifetime wager amount in cents
        },
        "summarizedBets": [          // Array of user betting summaries
            {
                "user": {
                    "username": string, // Username of the referred user
                    "avatar": string    // URL to user's avatar
                },
                "wager": number,      // Total amount wagered by this user in cents
                "bets": number        // Total number of bets placed by this user
            }
        ],
        "summary": {
            "totalUsers": number,     // Total number of unique users who have used your code
            "activeUsers": number,    // Number of users who placed bets in the selected period
            "totalBets": number,      // Total number of bets placed in the selected period
            "totalWager": number      // Total amount wagered in the selected period in cents
        },
        "dateRange": {
            "from": date,            // Start date of the query period
            "to": date               // End date of the query period
        },
        "processingTime": number     // Time taken to process the request in milliseconds
    }
}
```

#### Example Response
```json
{
    "error": false,
    "data": {
        "affiliate": {
            "id": 123,
            "code": "CREATOR123",
            "createdAt": "2025-01-01T00:00:00Z",
            "claimableBalance": 5000,
            "totalEarned": 15000,
            "totalWagered": 100000
        },
        "summarizedBets": [
            {
                "user": {
                    "username": "player1",
                    "avatar": "https://example.com/avatar1.jpg"
                },
                "wager": 10000,
                "bets": 50
            }
        ],
        "summary": {
            "totalUsers": 10,
            "activeUsers": 5,
            "totalBets": 150,
            "totalWager": 50000
        },
        "dateRange": {
            "from": "2025-01-24T00:00:00Z",
            "to": "2025-01-31T23:59:59Z"
        },
        "processingTime": 1234
    }
}
```

#### Error Responses
The API returns error responses in the following format:
```json
{
    "error": true,
    "msg": "Error message here",
    "retryable": boolean           // Indicates if the error is temporary and the request can be retried
}
```

#### Common Error Messages
- "Invalid API key format" - The provided API key is malformed or exceeds 100 characters
- "Invalid date format" - Dates must be in YYYY-MM-DD format
- "Invalid date range!" - The 'from' date must be before the 'to' date
- "Cannot query future dates" - The 'to' date cannot be in the future
- "Date range is too big! Max 100 days" - The date range cannot exceed 100 days
- "Invalid API key {apikey}" - The provided API key doesn't exist or is inactive
- "Affiliate not found!" - The affiliate account associated with the API key was not found
- "Server is busy processing other requests. Please try again in a few seconds." - Rate limit exceeded
- "Rate limit exceeded. Please try again in {X} seconds." - Cooldown period is still active

#### Limitations and Notes
- Maximum date range: 100 days
- Future dates are not allowed and will be capped to the current time
- API key must be valid and associated with an active affiliate account
- All monetary values are returned as integers (representing cents/smallest currency unit)
- Endpoint has a 5-minute cooldown between requests
- Results are paginated and sorted by total wager amount in descending order
- The response includes a processingTime field indicating how long the request took to process
- If no date range is specified, defaults to the last 7 days
- The summarizedBets array contains user data sorted by wager amount in descending order

#### Limitations
- Maximum date range: 100 days
- Future dates are not allowed
- API key must be valid and associated with an active affiliate account
- All monetary values are returned as integers (representing cents/smallest currency unit)
- Endpoint has a 5-minute cooldown between requests 