# Steam Profile Monitor ( parsing steam accounts)

A tool to automatically find Steam profiles that match specific criteria:
- Steam Level: 0-10
- CS:GO Inventory Value: > $500
- Activity Status: Active/Inactive

# issues 
1)the code can’t find steam profiles on its own
2)the code does not sort any accounts

# what can help ?
1)maybe adding a scraber will do it , however steam does not provide profiles ID's publically, that's why I tried doing it through cs go market
2)there is an extension in google that automatically gives you a price of an inventory , maybe it can be connected somehow to the code

## Setup Instructions 

1. **Install Python 3.8+** if not already installed

2. **Install required packages:**
   ```bash
   pip install -r requirements.txt
